# 不依赖 Python：用 .NET 移动鼠标
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Write-Host "Current cursor:" ([System.Windows.Forms.Cursor]::Position)
Write-Host "In 2 seconds, cursor should jump to (400,400) then (800,600)"
Start-Sleep -Seconds 2

[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(400, 400)
Start-Sleep -Milliseconds 800
Write-Host "Now:" ([System.Windows.Forms.Cursor]::Position)

[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(800, 600)
Start-Sleep -Milliseconds 800
Write-Host "Now:" ([System.Windows.Forms.Cursor]::Position)

Write-Host ""
Write-Host "If cursor DID NOT move, Windows is blocking synthetic mouse input"
Write-Host "(common with remote-control apps, or when launched from Cursor IDE)."
Write-Host "Fix: Win+R -> cmd -> cd /d D:\A_Project\chess -> play_red.bat"
Pause
