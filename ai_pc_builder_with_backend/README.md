# AI-Based PC Builder

Full-stack AI-Based PC Builder using Python Flask backend and HTML/CSS/JavaScript frontend.

## Project structure

```text
ai_pc_builder_backend/
├── backend/
│   ├── app.py
│   └── data/
│       └── PC_Components_Dataset_small.xlsx
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── script.js
├── requirements.txt
├── render.yaml
└── README.md
```

## Run locally

```bash
cd ai_pc_builder_backend
python -m venv venv
# Windows: venv\\Scripts\\activate
source venv/bin/activate
pip install -r requirements.txt
python backend/app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Deploy on Render

1. Upload this project to GitHub.
2. Go to Render > New > Web Service.
3. Connect the GitHub repository.
4. Use:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn backend.app:app`
5. Deploy.

The Flask app serves both the API and the frontend, so it works locally and online from the same URL.

## API

### `GET /api/components`
Returns loaded components from the Excel file.

### `POST /api/build`
Request body:

```json
{
  "budget": 1200,
  "purpose": "Gaming",
  "algorithm": "A*",
  "currency": "USD"
}
```

Returns selected compatible build, total price, explored states, algorithm used, score, and compatibility status.
