# Finance Automation

This project uses **[uv](https://docs.astral.sh/uv/)** for package management, which provides a modern, fast, and Node.js-like experience for Python.

## Node.js vs. UV Cheat Sheet

If you are coming from a Node.js background, here is how the commands map:

| Action | Node.js (npm) | Python (uv) |
| :--- | :--- | :--- |
| **Initialize Project** | `npm init` | `uv init` |
| **Install Dependencies** | `npm install` | `uv sync` |
| **Add a Package** | `npm install <pkg>` | `uv add <pkg>` |
| **Remove a Package** | `npm uninstall <pkg>` | `uv remove <pkg>` |
| **Run a Script** | `npm run <script>` | `uv run <script_or_file>` |
| **Package Manifest** | `package.json` | `pyproject.toml` |
| **Lockfile** | `package-lock.json` | `uv.lock` |

## Getting Started

1.  **Initialize/Sync**:
    Running `uv sync` will automatically create a virtual environment in `.venv/` and install all dependencies listed in `pyproject.toml`.

2.  **Adding Packages**:
    To add a library (e.g., pandas):
    ```bash
    uv add pandas
    ```

3.  **Running Code**:
    You don't need to manually "activate" the environment to run scripts. Just use `uv run`:
    ```bash
    uv run main.py
    ```

4.  **Activation (Optional)**:
    If your IDE needs the environment activated:
    ```bash
    source .venv/bin/activate
    ```
