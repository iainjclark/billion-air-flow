# NYC TLC Data Downloader
# Downloads trip record CSVs (Yellow, Green, FHV) from 2009–2025
# Destination: C:\raw\tlc_data

$baseUrl = "https://d37ci6vzurychx.cloudfront.net/trip-data"
$destDir = "C:\raw\tlc_data"

# Create destination directory if it doesn't exist
if (!(Test-Path -Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir | Out-Null
}

# Years to download (adjust if you want a subset)
$years = 2009..2025
$months = 1..12

# Dataset types
$datasets = @("yellow", "green", "fhvhv", "fhv")

foreach ($dataset in $datasets) {
    foreach ($year in $years) {
        foreach ($month in $months) {
            $file = "{0}_tripdata_{1:D4}-{2:D2}.parquet" -f $dataset, $year, $month
            $url = "$baseUrl/$file"
            $outFile = Join-Path $destDir $file

            if (!(Test-Path $outFile)) {
                try {
                    Write-Host "Downloading $url..."
                    Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing -TimeoutSec 600
                } catch {
                    Write-Warning "Failed to download $url"
                }
            } else {
                Write-Host "Already have $file, skipping..."
            }
        }
    }
}
