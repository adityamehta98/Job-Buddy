param(
    [string]$Source = (Join-Path $PSScriptRoot "..\assets\job-buddy-struggle-source.png")
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $PSScriptRoot
$staticDirectory = Join-Path $projectRoot "static"
New-Item -ItemType Directory -Path $staticDirectory -Force | Out-Null

$sourceBitmap = [System.Drawing.Bitmap]::FromFile((Resolve-Path $Source))
try {
    $minX = $sourceBitmap.Width
    $minY = $sourceBitmap.Height
    $maxX = 0
    $maxY = 0

    # The generated artwork is white linework on black. Detect the bright
    # linework to find a tight crop while preserving a little breathing room.
    for ($y = 0; $y -lt $sourceBitmap.Height; $y += 2) {
        for ($x = 0; $x -lt $sourceBitmap.Width; $x += 2) {
            $pixel = $sourceBitmap.GetPixel($x, $y)
            if ([Math]::Max($pixel.R, [Math]::Max($pixel.G, $pixel.B)) -gt 80) {
                $minX = [Math]::Min($minX, $x)
                $minY = [Math]::Min($minY, $y)
                $maxX = [Math]::Max($maxX, $x)
                $maxY = [Math]::Max($maxY, $y)
            }
        }
    }

    if ($minX -ge $maxX -or $minY -ge $maxY) {
        throw "Could not find the logo linework in the generated source image."
    }

    $contentWidth = $maxX - $minX + 1
    $contentHeight = $maxY - $minY + 1
    $squareSize = [Math]::Max($contentWidth, $contentHeight)
    $padding = [int]($squareSize * 0.10)
    $squareSize += $padding * 2
    $centerX = ($minX + $maxX) / 2
    $centerY = ($minY + $maxY) / 2
    $cropX = [int]($centerX - $squareSize / 2)
    $cropY = [int]($centerY - $squareSize / 2)
    $cropX = [Math]::Max(0, [Math]::Min($cropX, $sourceBitmap.Width - $squareSize))
    $cropY = [Math]::Max(0, [Math]::Min($cropY, $sourceBitmap.Height - $squareSize))
    $sourceRectangle = New-Object System.Drawing.Rectangle($cropX, $cropY, $squareSize, $squareSize)

    function New-LogoBitmap([int]$Size) {
        $bitmap = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.Clear([System.Drawing.Color]::Black)
            $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $destination = New-Object System.Drawing.Rectangle(0, 0, $Size, $Size)
            $graphics.DrawImage($sourceBitmap, $destination, $sourceRectangle, [System.Drawing.GraphicsUnit]::Pixel)
        }
        finally {
            $graphics.Dispose()
        }
        return $bitmap
    }

    $logo = New-LogoBitmap 512
    try {
        $logo.Save((Join-Path $staticDirectory "job-buddy-logo.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $logo.Dispose()
    }

    $sizes = @(16, 32, 48, 256)
    $images = @()
    foreach ($size in $sizes) {
        $bitmap = New-LogoBitmap $size
        $memory = New-Object System.IO.MemoryStream
        try {
            $bitmap.Save($memory, [System.Drawing.Imaging.ImageFormat]::Png)
            $images += ,$memory.ToArray()
        }
        finally {
            $bitmap.Dispose()
            $memory.Dispose()
        }
    }

    $iconPath = Join-Path $staticDirectory "job-buddy.ico"
    $stream = [System.IO.File]::Create($iconPath)
    $writer = New-Object System.IO.BinaryWriter($stream)
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$sizes.Count)
        $offset = 6 + (16 * $sizes.Count)
        for ($index = 0; $index -lt $sizes.Count; $index++) {
            $encodedSize = if ($sizes[$index] -eq 256) { 0 } else { $sizes[$index] }
            $writer.Write([byte]$encodedSize)
            $writer.Write([byte]$encodedSize)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]32)
            $writer.Write([uint32]$images[$index].Length)
            $writer.Write([uint32]$offset)
            $offset += $images[$index].Length
        }
        foreach ($image in $images) {
            $writer.Write($image)
        }
    }
    finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}
finally {
    $sourceBitmap.Dispose()
}
