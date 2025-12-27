"""CLI interface for continuous Claude."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import uuid4

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .ledger import Ledger, LearningCategory
from .runner import Runner, IterationLimit, CostLimit, NoNewLearnings
from .runner.stop_conditions import TimeLimit, CompositeStopCondition
from .search import SearchIndex
from .handoff import Handoff, HandoffManager


console = Console()


def get_global_ledger() -> Ledger:
    """Get or create the global ledger."""
    global_path = Path.home() / ".claude" / "ledger"
    return Ledger(global_path, is_global=True)


def get_project_ledger(project_path: Path) -> Ledger:
    """Get or create a project ledger."""
    ledger_path = project_path / ".claude" / "ledger"
    return Ledger(ledger_path, is_global=False)


@click.group()
@click.version_option()
def main():
    """Continuous Claude - Blockchain-style memory for iterative development."""
    pass


@main.command()
@click.argument("prompt")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
@click.option(
    "--max-iterations", "-n",
    type=int,
    default=10,
    help="Maximum iterations (default: 10)",
)
@click.option(
    "--max-cost",
    type=float,
    default=None,
    help="Maximum cost in USD",
)
@click.option(
    "--max-time",
    type=int,
    default=None,
    help="Maximum time in minutes",
)
@click.option(
    "--stale-threshold",
    type=int,
    default=3,
    help="Stop after N iterations with no new learnings",
)
def run(
    prompt: str,
    project: Path,
    max_iterations: int,
    max_cost: Optional[float],
    max_time: Optional[int],
    stale_threshold: int,
):
    """Run continuous Claude with the given prompt."""
    project = project.resolve()

    console.print(f"[bold]Project:[/bold] {project}")
    console.print(f"[bold]Prompt:[/bold] {prompt[:100]}...")

    # Set up ledgers
    project_ledger = get_project_ledger(project)
    global_ledger = get_global_ledger()

    # Build stop conditions
    conditions = [IterationLimit(max_iterations)]

    if max_cost:
        conditions.append(CostLimit(max_cost))

    if max_time:
        conditions.append(TimeLimit(timedelta(minutes=max_time)))

    conditions.append(NoNewLearnings(stale_threshold))

    # Create and run
    runner = Runner(
        project_path=project,
        project_ledger=project_ledger,
        global_ledger=global_ledger,
        stop_conditions=conditions,
    )

    result = runner.run(prompt)

    console.print(f"\n[bold green]Complete![/bold green]")
    console.print(f"Session ID: {result['session_id']}")


@main.command("list")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory (default: show global)",
)
@click.option(
    "--min-confidence", "-c",
    type=float,
    default=0.0,
    help="Minimum confidence to show",
)
@click.option(
    "--category",
    type=click.Choice(["discovery", "decision", "error", "pattern"]),
    default=None,
    help="Filter by category",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=20,
    help="Maximum results to show",
)
def list_learnings(
    project: Optional[Path],
    min_confidence: float,
    category: Optional[str],
    limit: int,
):
    """List learnings from the ledger."""
    if project:
        ledger = get_project_ledger(project.resolve())
        console.print(f"[bold]Project ledger:[/bold] {project}")
    else:
        ledger = get_global_ledger()
        console.print("[bold]Global ledger[/bold]")

    cat_filter = LearningCategory(category) if category else None
    learnings = ledger.get_learnings_by_confidence(
        min_confidence=min_confidence,
        category=cat_filter,
        limit=limit,
    )

    if not learnings:
        console.print("[dim]No learnings found[/dim]")
        return

    table = Table(title=f"Learnings ({len(learnings)})")
    table.add_column("ID", style="dim")
    table.add_column("Category", style="cyan")
    table.add_column("Confidence", style="green")
    table.add_column("Outcomes", style="yellow")

    for l in learnings:
        conf_pct = f"{l['confidence']*100:.0f}%"
        table.add_row(
            l["id"][:8],
            l["category"],
            conf_pct,
            str(l.get("outcome_count", 0)),
        )

    console.print(table)


@main.command()
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory (default: show global)",
)
def verify(project: Optional[Path]):
    """Verify ledger chain integrity."""
    if project:
        ledger = get_project_ledger(project.resolve())
        console.print(f"[bold]Verifying project ledger:[/bold] {project}")
    else:
        ledger = get_global_ledger()
        console.print("[bold]Verifying global ledger[/bold]")

    is_valid, errors = ledger.verify_chain()

    if is_valid:
        console.print("[bold green]Chain integrity verified![/bold green]")
        blocks = ledger.get_all_blocks()
        console.print(f"Total blocks: {len(blocks)}")
    else:
        console.print("[bold red]Chain integrity errors found![/bold red]")
        for error in errors:
            console.print(f"  - {error}")


@main.command()
@click.argument("learning_id")
@click.option(
    "--result", "-r",
    type=click.Choice(["success", "failure", "partial"]),
    required=True,
    help="Outcome result",
)
@click.option(
    "--context", "-c",
    type=str,
    required=True,
    help="Description of how the knowledge was applied",
)
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory (default: global)",
)
def outcome(
    learning_id: str,
    result: str,
    context: str,
    project: Optional[Path],
):
    """Record an outcome for a learning (affects confidence)."""
    from .ledger.models import OutcomeResult

    if project:
        ledger = get_project_ledger(project.resolve())
    else:
        ledger = get_global_ledger()

    # Find the learning
    found = False
    for block in ledger.get_all_blocks():
        for learning in block.learnings:
            if learning.id.startswith(learning_id):
                result_enum = OutcomeResult(result)
                learning.apply_outcome(result_enum, context)

                # Update the block file
                block_file = ledger.blocks_dir / f"{block.id}.json"
                ledger._write_json(block_file, block.model_dump(mode="json"))

                # Update reinforcements
                ledger.update_learning_confidence(learning.id, learning.confidence)

                console.print(f"[green]Recorded {result} outcome for learning {learning.id[:8]}[/green]")
                console.print(f"New confidence: {learning.confidence*100:.0f}%")
                found = True
                break
        if found:
            break

    if not found:
        console.print(f"[red]Learning {learning_id} not found[/red]")


@main.command()
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Project directory",
)
@click.option(
    "--threshold", "-t",
    type=float,
    default=0.8,
    help="Minimum confidence to promote (default: 0.8)",
)
def promote(project: Path, threshold: float):
    """Promote high-confidence project learnings to global ledger."""
    project_ledger = get_project_ledger(project.resolve())
    global_ledger = get_global_ledger()

    promoted = project_ledger.promote_to_global(global_ledger, threshold)

    if promoted:
        console.print(f"[green]Promoted {len(promoted)} learnings to global ledger[/green]")
        for lid in promoted:
            console.print(f"  - {lid[:8]}")
    else:
        console.print("[dim]No learnings met the threshold for promotion[/dim]")


@main.command()
@click.argument("learning_id")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory (default: global)",
)
def show(learning_id: str, project: Optional[Path]):
    """Show details of a specific learning."""
    if project:
        ledger = get_project_ledger(project.resolve())
    else:
        ledger = get_global_ledger()

    for block in ledger.get_all_blocks():
        for learning in block.learnings:
            if learning.id.startswith(learning_id):
                console.print(f"[bold]ID:[/bold] {learning.id}")
                console.print(f"[bold]Category:[/bold] {learning.category.value}")
                console.print(f"[bold]Confidence:[/bold] {learning.confidence*100:.0f}%")
                console.print(f"[bold]Source:[/bold] {learning.source or 'N/A'}")
                console.print(f"\n[bold]Content:[/bold]\n{learning.content}")

                if learning.outcomes:
                    console.print(f"\n[bold]Outcomes ({len(learning.outcomes)}):[/bold]")
                    for o in learning.outcomes:
                        console.print(f"  - {o.result.value}: {o.context} (delta: {o.delta:+.2f})")

                return

    console.print(f"[red]Learning {learning_id} not found[/red]")


@main.command()
@click.argument("query")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory (default: global)",
)
@click.option(
    "--category",
    type=click.Choice(["discovery", "decision", "error", "pattern"]),
    default=None,
    help="Filter by category",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=20,
    help="Maximum results to show",
)
def search(
    query: str,
    project: Optional[Path],
    category: Optional[str],
    limit: int,
):
    """Search learnings using full-text search.

    Supports FTS5 query syntax including:
    - Simple terms: authentication
    - Phrases: "JWT token"
    - Boolean operators: auth AND token
    - Prefix matching: auth*
    """
    # Get the appropriate search index
    if project:
        cache_dir = project.resolve() / ".claude" / "cache"
    else:
        cache_dir = Path.home() / ".claude" / "cache"

    cache_dir.mkdir(parents=True, exist_ok=True)
    index = SearchIndex(cache_dir / "search.db")

    try:
        if category:
            results = index.search_by_category(query, category, limit=limit)
        else:
            results = index.search(query, limit=limit)

        if not results:
            console.print(f"[dim]No results found for '{query}'[/dim]")
            return

        table = Table(title=f"Search Results ({len(results)})")
        table.add_column("ID", style="dim", width=8)
        table.add_column("Category", style="cyan", width=10)
        table.add_column("Confidence", style="green", width=10)
        table.add_column("Snippet", style="white")

        for result in results:
            conf_pct = f"{result.confidence*100:.0f}%"
            # Clean up snippet for display (remove HTML marks for terminal)
            snippet = result.snippet.replace("<mark>", "[bold yellow]").replace("</mark>", "[/bold yellow]")
            table.add_row(
                result.learning_id[:8],
                result.category,
                conf_pct,
                snippet,
            )

        console.print(table)

    finally:
        index.close()


@main.command()
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory (default: global)",
)
def reindex(project: Optional[Path]):
    """Rebuild the search index from the ledger.

    Use this after importing learnings or if the index becomes corrupted.
    """
    # Get the appropriate ledger and search index
    if project:
        project = project.resolve()
        ledger = get_project_ledger(project)
        cache_dir = project / ".claude" / "cache"
        console.print(f"[bold]Reindexing project ledger:[/bold] {project}")
    else:
        ledger = get_global_ledger()
        cache_dir = Path.home() / ".claude" / "cache"
        console.print("[bold]Reindexing global ledger[/bold]")

    cache_dir.mkdir(parents=True, exist_ok=True)
    index = SearchIndex(cache_dir / "search.db")

    try:
        count = index.reindex_ledger(ledger)
        console.print(f"[green]Successfully indexed {count} learnings[/green]")

        # Show stats
        stats = index.get_stats()
        if stats["by_category"]:
            console.print("\n[bold]By category:[/bold]")
            for cat, cnt in stats["by_category"].items():
                console.print(f"  - {cat}: {cnt}")

    finally:
        index.close()


@main.group()
def handoff():
    """Manage work-in-progress handoffs."""
    pass


@handoff.command("create")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
@click.option(
    "--session", "-s",
    type=str,
    default=None,
    help="Session ID (default: auto-generated)",
)
@click.option(
    "--completed",
    multiple=True,
    help="Completed tasks (can be specified multiple times)",
)
@click.option(
    "--pending", "-t",
    multiple=True,
    help="Pending tasks (can be specified multiple times)",
)
@click.option(
    "--blocker", "-b",
    multiple=True,
    help="Blockers (can be specified multiple times)",
)
@click.option(
    "--context", "-n",
    type=str,
    default="",
    help="Additional context notes",
)
def handoff_create(
    project: Path,
    session: Optional[str],
    completed: tuple[str, ...],
    pending: tuple[str, ...],
    blocker: tuple[str, ...],
    context: str,
):
    """Create a new handoff for the current session."""
    project = project.resolve()
    session_id = session or str(uuid4())[:8]

    manager = HandoffManager(project)
    handoff_obj = manager.create_handoff(
        session_id=session_id,
        completed_tasks=list(completed) if completed else None,
        pending_tasks=list(pending) if pending else None,
        blockers=list(blocker) if blocker else None,
        context_notes=context,
    )

    file_path = manager.save_handoff(handoff_obj)

    console.print(f"[green]Created handoff for session {session_id}[/green]")
    console.print(f"[dim]Saved to: {file_path}[/dim]")

    # Show summary
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Completed tasks: {len(handoff_obj.completed_tasks)}")
    console.print(f"  Pending tasks: {len(handoff_obj.pending_tasks)}")
    console.print(f"  Blockers: {len(handoff_obj.blockers)}")
    console.print(f"  Modified files: {len(handoff_obj.modified_files)}")


@handoff.command("show")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
@click.option(
    "--session", "-s",
    type=str,
    default=None,
    help="Filter by session ID",
)
def handoff_show(project: Path, session: Optional[str]):
    """Show the latest handoff."""
    project = project.resolve()
    manager = HandoffManager(project)

    handoff_obj = manager.load_latest_handoff(session_id=session)

    if not handoff_obj:
        console.print("[dim]No handoffs found[/dim]")
        return

    # Display handoff in a panel
    lines = [
        f"[bold]Session:[/bold] {handoff_obj.session_id}",
        f"[bold]Timestamp:[/bold] {handoff_obj.timestamp.isoformat()}",
        "",
    ]

    if handoff_obj.completed_tasks:
        lines.append("[bold cyan]Completed:[/bold cyan]")
        for task in handoff_obj.completed_tasks:
            lines.append(f"  - {task}")
        lines.append("")

    if handoff_obj.pending_tasks:
        lines.append("[bold yellow]Pending:[/bold yellow]")
        for task in handoff_obj.pending_tasks:
            lines.append(f"  - {task}")
        lines.append("")

    if handoff_obj.blockers:
        lines.append("[bold red]Blockers:[/bold red]")
        for blocker in handoff_obj.blockers:
            lines.append(f"  - {blocker}")
        lines.append("")

    if handoff_obj.modified_files:
        lines.append("[bold]Modified Files:[/bold]")
        for fp in handoff_obj.modified_files[:15]:
            lines.append(f"  - {fp}")
        if len(handoff_obj.modified_files) > 15:
            lines.append(f"  ... and {len(handoff_obj.modified_files) - 15} more")
        lines.append("")

    if handoff_obj.context_notes:
        lines.append("[bold]Context:[/bold]")
        lines.append(handoff_obj.context_notes)

    panel = Panel("\n".join(lines), title="Latest Handoff", border_style="blue")
    console.print(panel)


@handoff.command("list")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
@click.option(
    "--session", "-s",
    type=str,
    default=None,
    help="Filter by session ID",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=10,
    help="Maximum number of handoffs to show (default: 10)",
)
def handoff_list(project: Path, session: Optional[str], limit: int):
    """List available handoffs."""
    project = project.resolve()
    manager = HandoffManager(project)

    handoffs = manager.list_handoffs(session_id=session, limit=limit)

    if not handoffs:
        console.print("[dim]No handoffs found[/dim]")
        return

    table = Table(title=f"Handoffs ({len(handoffs)})")
    table.add_column("Session", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Completed", style="green")
    table.add_column("Pending", style="yellow")
    table.add_column("Blockers", style="red")
    table.add_column("Files", style="blue")

    for h in handoffs:
        table.add_row(
            h["session_id"][:12],
            h["timestamp"][:19],
            str(h["completed_count"]),
            str(h["pending_count"]),
            str(h["blocker_count"]),
            str(h["modified_files_count"]),
        )

    console.print(table)


if __name__ == "__main__":
    main()
