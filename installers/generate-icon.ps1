<#
.SYNOPSIS
    Generate AI Orchestrator icon (256x256 .ico) without external tools
#>

$outputPath = Join-Path $PSScriptRoot "icon.ico"

function New-IconFromBitmap {
    param([byte[]]$BitmapBytes, [string]$OutputPath)
    Add-Type -AssemblyName System.Drawing

    try {
        $ms = [System.IO.MemoryStream]::new($BitmapBytes)
        $bmp = [System.Drawing.Bitmap]::FromStream($ms)

        # Create icon from bitmap
        $hIcon = $bmp.GetHicon()
        $icon = [System.Drawing.Icon]::FromHandle($hIcon)

        $fs = [System.IO.FileStream]::new($OutputPath, [System.IO.FileMode]::Create)
        $icon.Save($fs)
        $fs.Close()

        $icon.Dispose()
        $bmp.Dispose()
        $ms.Dispose()
        return $true
    } catch {
        return $false
    }
}

function Generate-AIOrchestratorIcon {
    $size = 256
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality

    try {
        # Background gradient (dark blue-purple)
        $rect = [System.Drawing.Rectangle]::new(0, 0, $size, $size)
        $brush = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
            $rect,
            [System.Drawing.Color]::FromArgb(255, 30, 30, 60),
            [System.Drawing.Color]::FromArgb(255, 20, 20, 40),
            [System.Drawing.Drawing2D.LinearGradientMode]::Vertical
        )
        $g.FillRectangle($brush, $rect)

        # Draw AI "brain" arc (neural network style)
        $pen = [System.Drawing.Pen]::new([System.Drawing.Color]::Cyan, 3)
        $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round

        # Nodes (circles)
        $nodes = @(
            @{x=80; y=60; c=[System.Drawing.Color]::Magenta},
            @{x=176; y=60; c=[System.Drawing.Color]::Cyan},
            @{x=50; y=140; c=[System.Drawing.Color]::Orange},
            @{x=128; y=128; c=[System.Drawing.Color]::Lime},
            @{x=206; y=140; c=[System.Drawing.Color]::Yellow},
            @{x=80; y=196; c=[System.Drawing.Color]::Cyan},
            @{x=176; y=196; c=[System.Drawing.Color]::Magenta}
        )

        # Connections
        $connections = @(
            @(0,1), @(0,2), @(0,3), @(1,3), @(1,4),
            @(2,3), @(2,5), @(3,4), @(3,5), @(3,6),
            @(4,6), @(5,6)
        )

        $linePen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(80, 100, 200, 255), 2)
        foreach ($conn in $connections) {
            $n1 = $nodes[$conn[0]]
            $n2 = $nodes[$conn[1]]
            $g.DrawLine($linePen, $n1.x, $n1.y, $n2.x, $n2.y)
        }

        # Draw nodes
        foreach ($node in $nodes) {
            $b = [System.Drawing.SolidBrush]::new($node.c)
            $size_n = 16
            $g.FillEllipse($b, $node.x - $size_n/2, $node.y - $size_n/2, $size_n, $size_n)
            $b.Dispose()
        }

        # Text "AI" in glow
        $font = [System.Drawing.Font]::new("Segoe UI", 48, [System.Drawing.FontStyle]::Bold)
        $textBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
        $g.DrawString("AI", $font, $textBrush, 60, 180)
        $textBrush.Dispose()
        $font.Dispose()

        # Border
        $borderPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(60, 100, 200, 255), 2)
        $g.DrawRectangle($borderPen, 1, 1, $size-3, $size-3)

        # Save as PNG first
        $pngPath = [System.IO.Path]::GetTempFileName() + ".png"
        $bmp.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)

        # Read PNG bytes and convert to icon
        $pngBytes = [System.IO.File]::ReadAllBytes($pngPath)
        $result = New-IconFromBitmap -BitmapBytes $pngBytes -OutputPath $outputPath

        Remove-Item $pngPath -Force -ErrorAction SilentlyContinue
        return $result
    } finally {
        $g.Dispose()
        $bmp.Dispose()
    }
}

# Main
if (Generate-AIOrchestratorIcon) {
    Write-Host "[+] Icon generated: $outputPath" -ForegroundColor Green
} else {
    Write-Host "[!] Failed to generate icon" -ForegroundColor Red
}