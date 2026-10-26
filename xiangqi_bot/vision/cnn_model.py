"""小型棋子分类 CNN（训练与导出共用）。"""

from __future__ import annotations

import torch
import torch.nn as nn

from .cls_common import CLASS_CHARS, IMG_SIZE


class PieceCNN(nn.Module):
    """约 100k 参数，CPU 可实时推理。"""

    def __init__(self, n_classes: int = len(CLASS_CHARS)):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(128, 128, 3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.35),
            nn.Linear(128, 64),
            nn.ReLU(inplace=True),
            nn.Dropout(0.25),
            nn.Linear(64, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def build_model(n_classes: int = len(CLASS_CHARS)) -> PieceCNN:
    return PieceCNN(n_classes=n_classes)


def export_onnx(model: nn.Module, path: str, img_size: int = IMG_SIZE) -> None:
    model.eval()
    dummy = torch.zeros(1, 3, img_size, img_size)
    # Torch 2.14+ 默认 dynamo 导出器；legacy 更稳
    torch.onnx.export(
        model,
        dummy,
        path,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
