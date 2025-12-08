# Talos: AI-Powered Collaborative Workspace

Our graduation project implementing Retrieval-Augmented Generation (RAG) systems with a modular architecture,
to enhance team collaboration and project management.

## Quick Start

### Clone Repository

```bash
git clone https://github.com/Ab-romia/gp-artifact.git
cd gp-artifact
```

### Install Dependencies

> It is recommended to use [uv](https://docs.astral.sh/uv/).
> Install via `pip install uv`.

```bash
uv venv
uv sync
```

### Set Environment Variables
Copy the example env file, then edit `.env`.


```bash
cp .env.example .env
```

Add your API keys and other configurations.

### Start Dev Database:

```bash
docker compose up -d
```

### Run the Application

```bash
# Run the RAG CLI
uv run rag_cli.py

# Run the web app
uv run app.py
```


## Documentation

Detailed documentation is available in the [docs](./docs) directory. (TODO)
