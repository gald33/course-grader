from __future__ import annotations

import io
import signal
from dataclasses import dataclass
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter


class NotebookTimeoutError(RuntimeError):
    pass


@dataclass
class NotebookExecutionResult:
    ok_cells: int
    failed_cells: int
    run_ratio: float
    penalty_multiplier: float
    timed_out: bool
    error_summary: str
    executed_notebook: dict
    html: str
    logs: str


class _TimeoutGuard:
    def __init__(self, seconds: int):
        self.seconds = seconds

    def __enter__(self):
        def _handler(signum, frame):  # noqa: ARG001
            raise NotebookTimeoutError(f"Notebook execution exceeded {self.seconds} seconds")

        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(self.seconds)

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        signal.alarm(0)
        return False


def _is_nonempty_code_cell(cell: dict) -> bool:
    return cell.get("cell_type") == "code" and (cell.get("source") or "").strip() != ""


def _cell_failed(cell: dict) -> bool:
    for output in cell.get("outputs", []):
        if output.get("output_type") == "error":
            return True
    return False


def _collect_logs(cells: list[dict]) -> str:
    chunks: list[str] = []
    for idx, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        if not (cell.get("source") or "").strip():
            continue
        chunks.append(f"\n=== Cell {idx} ===\n")
        for output in cell.get("outputs", []):
            otype = output.get("output_type")
            if otype == "stream":
                chunks.append(output.get("text", ""))
            elif otype == "error":
                chunks.append("\n".join(output.get("traceback", [])) + "\n")
            elif otype in {"execute_result", "display_data"}:
                data = output.get("data", {})
                if "text/plain" in data:
                    chunks.append(str(data["text/plain"]) + "\n")
    return "".join(chunks).strip()


def execute_notebook(
    notebook_path: str | Path,
    total_timeout_seconds: int,
    penalty_power: float,
) -> NotebookExecutionResult:
    notebook_path = Path(notebook_path)
    nb = nbformat.read(str(notebook_path), as_version=4)

    client = NotebookClient(
        nb,
        timeout=None,
        kernel_name="python3",
        allow_errors=True,
        resources={"metadata": {"path": str(notebook_path.parent)}},
    )

    timed_out = False
    raised_error: Exception | None = None

    try:
        with _TimeoutGuard(total_timeout_seconds):
            client.execute()
    except NotebookTimeoutError:
        timed_out = True
    except Exception as exc:  # noqa: BLE001
        raised_error = exc

    code_cells = [c for c in nb.cells if _is_nonempty_code_cell(c)]
    ok_cells = 0
    failed_cells = 0

    for cell in code_cells:
        if _cell_failed(cell):
            failed_cells += 1
            continue

        if cell.get("execution_count") is None:
            if timed_out or raised_error is not None:
                failed_cells += 1
                continue
        ok_cells += 1

    denominator = ok_cells + failed_cells
    run_ratio = (ok_cells / denominator) if denominator > 0 else 1.0
    penalty = run_ratio**penalty_power

    html_exporter = HTMLExporter()
    body, _ = html_exporter.from_notebook_node(nb)

    logs = _collect_logs(nb.cells)
    if timed_out:
        logs += "\n\n[timeout] Notebook execution reached the hard timeout. Remaining cells marked failed."
    if raised_error is not None:
        logs += f"\n\n[fatal_error] {raised_error}"

    error_summary = ""
    if timed_out:
        error_summary = f"Execution timed out after {total_timeout_seconds} seconds"
    elif raised_error is not None:
        error_summary = str(raised_error)

    return NotebookExecutionResult(
        ok_cells=ok_cells,
        failed_cells=failed_cells,
        run_ratio=round(run_ratio, 6),
        penalty_multiplier=round(penalty, 6),
        timed_out=timed_out,
        error_summary=error_summary,
        executed_notebook=nb,
        html=body,
        logs=logs,
    )


def serialize_notebook(nb_obj: dict) -> bytes:
    stream = io.StringIO()
    nbformat.write(nb_obj, stream)
    return stream.getvalue().encode("utf-8")
