# Sector Cloud Experiment

This experiment builds a standalone sector treemap from the current ranking cache.

## Generate

```powershell
.\.venv\Scripts\python.exe -B experiments\sector_cloud\generate_sector_cloud.py --window 10
```

Open `experiments/sector_cloud/output/index_w10.html` or `experiments/sector_cloud/output/index_w20.html` in a browser, or serve the output folder with a static server. `index.html` points to the latest generated window.

```powershell
python -m http.server 8090 -d experiments\sector_cloud\output
```

Then visit `http://127.0.0.1:8090/`.
