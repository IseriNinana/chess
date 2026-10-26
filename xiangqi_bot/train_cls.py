"""训练棋子小 CNN 并导出 ONNX。"""

from __future__ import annotations

import json
import random
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from .vision.cls_common import (
    CLASS_CHARS,
    IMG_SIZE,
    char_to_folder,
    ensure_class_dirs,
    list_dataset_images,
)
from .vision.cnn_model import build_model, export_onnx


class PieceDataset(Dataset):
    def __init__(self, items: list[tuple[Path, int]], augment: bool = False):
        self.items = items
        self.augment = augment

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, idx: int):
        path, label = self.items[idx]
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            img = np.zeros((IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)
        if self.augment:
            img = _augment(img)
        img = cv2.resize(img, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = torch.from_numpy(np.transpose(rgb, (2, 0, 1)).copy())
        return x, label


def _augment(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    # 旋转 ±12°
    angle = random.uniform(-12, 12)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, random.uniform(0.9, 1.1))
    img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
    # 平移
    tx, ty = random.randint(-4, 4), random.randint(-4, 4)
    M2 = np.float32([[1, 0, tx], [0, 1, ty]])
    img = cv2.warpAffine(img, M2, (w, h), borderMode=cv2.BORDER_REFLECT_101)
    alpha = random.uniform(0.7, 1.3)
    beta = random.uniform(-30, 30)
    img = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
    if random.random() < 0.25:
        img = cv2.GaussianBlur(img, (3, 3), 0)
    if random.random() < 0.2:
        noise = np.random.randint(-15, 16, img.shape, dtype=np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def _split(items: list[tuple[Path, int]], val_ratio: float = 0.15, seed: int = 0):
    by_cls: dict[int, list[tuple[Path, int]]] = {i: [] for i in range(len(CLASS_CHARS))}
    for it in items:
        by_cls[it[1]].append(it)
    train, val = [], []
    rng = random.Random(seed)
    for cls_items in by_cls.values():
        rng.shuffle(cls_items)
        n_val = max(1, int(len(cls_items) * val_ratio)) if len(cls_items) >= 5 else 0
        val.extend(cls_items[:n_val])
        train.extend(cls_items[n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def _class_weights(items: list[tuple[Path, int]]) -> torch.Tensor:
    counts = np.zeros(len(CLASS_CHARS), dtype=np.float64)
    for _, y in items:
        counts[y] += 1
    counts = np.maximum(counts, 1.0)
    w = counts.sum() / (len(CLASS_CHARS) * counts)
    return torch.tensor(w, dtype=torch.float32)


def _sampler(items: list[tuple[Path, int]]) -> WeightedRandomSampler:
    counts = np.zeros(len(CLASS_CHARS), dtype=np.float64)
    for _, y in items:
        counts[y] += 1
    counts = np.maximum(counts, 1.0)
    weights = [1.0 / counts[y] for _, y in items]
    return WeightedRandomSampler(weights, num_samples=len(items), replacement=True)


@torch.no_grad()
def _eval(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[float, float]:
    model.eval()
    correct = total = 0
    loss_sum = 0.0
    crit = nn.CrossEntropyLoss()
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        logits = model(x)
        loss_sum += float(crit(logits, y)) * len(y)
        pred = logits.argmax(dim=1)
        correct += int((pred == y).sum())
        total += len(y)
    if total == 0:
        return 0.0, 0.0
    return loss_sum / total, correct / total


def train_cls(
    dataset_dir: Path,
    out_dir: Path,
    epochs: int = 40,
    batch_size: int = 64,
    lr: float = 1e-3,
    img_size: int = IMG_SIZE,
) -> Path:
    _ = img_size
    items = list_dataset_images(dataset_dir)
    if len(items) < 30:
        raise RuntimeError(
            f"样本太少 ({len(items)})。请先: python main.py collect-cls --bootstrap-templates "
            "或 --assume-start"
        )

    print(f"样本总数: {len(items)}")
    for i, ch in enumerate(CLASS_CHARS):
        n = sum(1 for _, y in items if y == i)
        print(f"  {char_to_folder(ch):10s} {n}")

    train_items, val_items = _split(items)
    if not val_items:
        val_items = train_items[: max(1, len(train_items) // 10)]

    train_ds = PieceDataset(train_items, augment=True)
    val_ds = PieceDataset(val_items, augment=False)
    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        sampler=_sampler(train_items),
        num_workers=0,
    )
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"设备: {device}")
    model = build_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(epochs, 1))
    crit = nn.CrossEntropyLoss(weight=_class_weights(train_items).to(device))

    out_dir.mkdir(parents=True, exist_ok=True)
    best_acc = -1.0
    best_path = out_dir / "piece_cls_best.pt"
    history = []

    for epoch in range(1, epochs + 1):
        model.train()
        run_loss = 0.0
        n = 0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            logits = model(x)
            loss = crit(logits, y)
            loss.backward()
            opt.step()
            run_loss += float(loss.detach()) * len(y)
            n += len(y)
        sched.step()
        tr_loss = run_loss / max(n, 1)
        va_loss, va_acc = _eval(model, val_loader, device)
        history.append({"epoch": epoch, "train_loss": tr_loss, "val_loss": va_loss, "val_acc": va_acc})
        print(f"epoch {epoch:03d}  train_loss={tr_loss:.4f}  val_loss={va_loss:.4f}  val_acc={va_acc:.3f}")
        if va_acc >= best_acc:
            best_acc = va_acc
            torch.save(
                {
                    "model": model.state_dict(),
                    "classes": CLASS_CHARS,
                    "img_size": IMG_SIZE,
                    "val_acc": va_acc,
                },
                best_path,
            )

    # 加载最佳并导出
    ckpt = torch.load(best_path, map_location="cpu", weights_only=False)
    model.load_state_dict(ckpt["model"])
    model.eval()
    onnx_path = out_dir / "piece_cls.onnx"
    export_onnx(model.cpu(), str(onnx_path))
    meta = {
        "classes": CLASS_CHARS,
        "img_size": IMG_SIZE,
        "best_val_acc": best_acc,
        "onnx": str(onnx_path),
        "checkpoint": str(best_path),
        "history": history,
    }
    (out_dir / "piece_cls_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"最佳 val_acc={best_acc:.3f}")
    print(f"已保存: {best_path}")
    print(f"已导出: {onnx_path}")
    return onnx_path


def run_train_cls(cfg: dict, epochs: int = 40, batch_size: int = 64, lr: float = 1e-3) -> None:
    from .config import project_root

    vis = cfg["vision"]
    ds = Path(vis.get("cls_dataset") or "data/cls_dataset")
    if not ds.is_absolute():
        ds = project_root() / ds
    out = Path(vis.get("cnn_model") or "data/models/piece_cls.onnx").parent
    if not out.is_absolute():
        out = project_root() / out
    ensure_class_dirs(ds)
    train_cls(ds, out, epochs=epochs, batch_size=batch_size, lr=lr)
