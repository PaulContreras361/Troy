# Troy

Personal AI Assistant powered by Streamlit and OpenAI.

## Requirements

- Python 3.11+ recommended
- `streamlit`
- `openai`

## Setup

1. Install dependencies:

```bash
git clone https://github.com/PaulContreras361/Troy.git
cd Troy
python3 -m pip install -r requirements.txt
```

2. Provide your OpenAI API key:

- Set the environment variable:

```bash
export OPENAI_API_KEY="your-api-key"
```

- Or paste it in the Streamlit sidebar after launching the app.

Alternatively, persist the key locally so you don't need to re-enter it:

- Create a file at `.streamlit/secrets.toml` with this content (do NOT commit it):

```toml
OPENAI_API_KEY = "your-api-key"
```

Streamlit will automatically load keys from `.streamlit/secrets.toml` and `app.py` will prefer the sidebar input, then the secrets file, then the environment variable.

## Run

```bash
streamlit run app.py
```

## GitHub Codespaces

If you are running this project in GitHub Codespaces:

- Open the `Ports` panel
- Find port `8501` or `8503`
- Click the forwarded preview/public URL for that port
- Do not manually type malformed URLs such as `https://-8501.app.github.dev/`

## Streamlit Community Cloud Deployment

This repository is ready for Streamlit Community Cloud.

1. Make sure `app.py` is in the repository root.
2. Make sure `requirements.txt` includes:
   - `streamlit==1.58.0`
   - `openai==2.43.0`
   - `Pillow>=9.0.0`
3. Connect your GitHub repo to Streamlit Community Cloud.
4. Choose the branch to deploy, then deploy the app.
5. Add your OpenAI API key in the Streamlit Cloud secrets manager:

```toml
OPENAI_API_KEY = "your-api-key"
```

6. Do not commit your actual `secrets.toml` to the repository.

This project also includes `.streamlit/config.toml` so Streamlit runs in headless mode with CORS disabled.

## Usage

- Enter a prompt in the chat input.
- Use the sidebar to add your OpenAI API key, select a model, or clear the chat history.
- `gpt-3.5-turbo` is the default model for general use.

