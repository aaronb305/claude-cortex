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
from .summaries import Summary, SummaryManager
from .suggestions import LearningRecommender


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
@click.option(
    "--show-decay", "-d",
    is_flag=True,
    default=False,
    help="Show both stored and effective (decayed) confidence",
)
def list_learnings(
    project: Optional[Path],
    min_confidence: float,
    category: Optional[str],
    limit: int,
    show_decay: bool,
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
    if show_decay:
        table.add_column("Stored", style="green")
        table.add_column("Effective", style="yellow")
    else:
        table.add_column("Confidence", style="green")
    table.add_column("Outcomes", style="yellow")

    for l in learnings:
        stored_pct = f"{l['confidence']*100:.0f}%"
        effective_pct = f"{l.get('effective_confidence', l['confidence'])*100:.0f}%"

        if show_decay:
            table.add_row(
                l["id"][:8],
                l["category"],
                stored_pct,
                effective_pct,
                str(l.get("outcome_count", 0)),
            )
        else:
            table.add_row(
                l["id"][:8],
                l["category"],
                effective_pct,
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
    """Record an outcome for a learning (affects confidence).

    Outcomes are stored in reinforcements.json to preserve block immutability.
    Block files are never modified after creation to maintain hash integrity.
    """
    from .ledger.models import OutcomeResult

    if project:
        ledger = get_project_ledger(project.resolve())
    else:
        ledger = get_global_ledger()

    # Use record_outcome which stores outcomes in reinforcements.json
    # instead of modifying block files (preserves hash integrity)
    result_enum = OutcomeResult(result)
    success, new_confidence, matched_id = ledger.record_outcome(learning_id, result_enum, context)

    if success:
        console.print(f"[green]Recorded {result} outcome for learning {matched_id[:8]}[/green]")
        console.print(f"New confidence: {new_confidence*100:.0f}%")
    else:
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
@click.option(
    "--show-decay", "-d",
    is_flag=True,
    default=False,
    help="Show both stored and effective (decayed) confidence",
)
def show(learning_id: str, project: Optional[Path], show_decay: bool):
    """Show details of a specific learning."""
    if project:
        ledger = get_project_ledger(project.resolve())
    else:
        ledger = get_global_ledger()

    # Find the learning efficiently using the new lookup method
    learning, block = ledger.get_learning_by_id(learning_id, prefix_match=True)

    if learning:
        console.print(f"[bold]ID:[/bold] {learning.id}")
        console.print(f"[bold]Category:[/bold] {learning.category.value}")

        if show_decay:
            effective_conf = ledger.get_effective_confidence(learning.id)
            console.print(f"[bold]Stored Confidence:[/bold] {learning.confidence*100:.0f}%")
            console.print(f"[bold]Effective Confidence:[/bold] {effective_conf*100:.0f}%")
            if learning.last_applied:
                console.print(f"[bold]Last Applied:[/bold] {learning.last_applied.isoformat()}")
            if learning.created_at:
                console.print(f"[bold]Created At:[/bold] {learning.created_at.isoformat()}")
        else:
            effective_conf = ledger.get_effective_confidence(learning.id)
            console.print(f"[bold]Confidence:[/bold] {effective_conf*100:.0f}%")

        console.print(f"[bold]Source:[/bold] {learning.source or 'N/A'}")
        console.print(f"\n[bold]Content:[/bold]\n{learning.content}")

        # Get outcomes from reinforcements.json (where they are now stored)
        outcomes = ledger.get_learning_outcomes(learning.id)
        if outcomes:
            console.print(f"\n[bold]Outcomes ({len(outcomes)}):[/bold]")
            for o in outcomes:
                console.print(f"  - {o['result']}: {o['context']} (delta: {o['delta']:+.2f})")
    else:
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

    with SearchIndex(cache_dir / "search.db") as index:
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

    with SearchIndex(cache_dir / "search.db") as index:
        count = index.reindex_ledger(ledger)
        console.print(f"[green]Successfully indexed {count} learnings[/green]")

        # Show stats
        stats = index.get_stats()
        if stats["by_category"]:
            console.print("\n[bold]By category:[/bold]")
            for cat, cnt in stats["by_category"].items():
                console.print(f"  - {cat}: {cnt}")


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


@main.group()
def summary():
    """Manage session summaries."""
    pass


@summary.command("show")
@click.argument("session_id", required=False)
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
def summary_show(session_id: Optional[str], project: Path):
    """Show summary for a session.

    If SESSION_ID is not provided, shows the most recent summary.
    """
    project = project.resolve()
    manager = SummaryManager(project)

    summary_obj = manager.load_latest_summary(session_id=session_id)

    if not summary_obj:
        console.print("[dim]No summaries found[/dim]")
        return

    # Display summary in a panel
    lines = [
        f"[bold]Session:[/bold] {summary_obj.session_id}",
        f"[bold]Timestamp:[/bold] {summary_obj.timestamp.isoformat()}",
        "",
    ]

    if summary_obj.summary_text:
        lines.append("[bold cyan]Summary:[/bold cyan]")
        lines.append(summary_obj.summary_text)
        lines.append("")

    if summary_obj.key_decisions:
        lines.append("[bold yellow]Key Decisions:[/bold yellow]")
        for decision in summary_obj.key_decisions:
            lines.append(f"  - {decision}")
        lines.append("")

    if summary_obj.files_discussed:
        lines.append("[bold]Files Discussed:[/bold]")
        for fp in summary_obj.files_discussed[:20]:
            lines.append(f"  - {fp}")
        if len(summary_obj.files_discussed) > 20:
            lines.append(f"  ... and {len(summary_obj.files_discussed) - 20} more")
        lines.append("")

    if summary_obj.learning_ids:
        lines.append("[bold green]Learnings Captured:[/bold green]")
        for lid in summary_obj.learning_ids[:10]:
            lines.append(f"  - {lid[:8]}")
        if len(summary_obj.learning_ids) > 10:
            lines.append(f"  ... and {len(summary_obj.learning_ids) - 10} more")

    panel = Panel("\n".join(lines), title="Session Summary", border_style="green")
    console.print(panel)


@summary.command("list")
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
    default=20,
    help="Maximum number of summaries to show (default: 20)",
)
def summary_list(project: Path, session: Optional[str], limit: int):
    """List available summaries."""
    project = project.resolve()
    manager = SummaryManager(project)

    summaries = manager.list_summaries(session_id=session, limit=limit)

    if not summaries:
        console.print("[dim]No summaries found[/dim]")
        return

    table = Table(title=f"Summaries ({len(summaries)})")
    table.add_column("Session", style="cyan", width=12)
    table.add_column("Timestamp", style="dim", width=19)
    table.add_column("Decisions", style="yellow", width=9)
    table.add_column("Files", style="blue", width=6)
    table.add_column("Learnings", style="green", width=9)
    table.add_column("Preview", style="white")

    for s in summaries:
        table.add_row(
            s["session_id"][:12],
            s["timestamp"][:19],
            str(s["decisions_count"]),
            str(s["files_count"]),
            str(s["learnings_count"]),
            s["summary_preview"][:50],
        )

    console.print(table)


@main.command()
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=10,
    help="Maximum suggestions to show (default: 10)",
)
@click.option(
    "--min-confidence", "-c",
    type=float,
    default=0.5,
    help="Minimum confidence threshold (default: 0.5)",
)
@click.option(
    "--apply",
    type=str,
    default=None,
    help="Import a suggested learning by ID (prefix match)",
)
def suggest(
    project: Path,
    limit: int,
    min_confidence: float,
    apply: Optional[str],
):
    """Show suggested learnings from global ledger for current project.

    Analyzes the current project to find relevant learnings from your
    global knowledge base. Use --apply to import a suggestion to the
    project ledger.
    """
    project = project.resolve()
    global_ledger = get_global_ledger()

    # Handle apply/import case
    if apply:
        project_ledger = get_project_ledger(project)

        # Import the learning
        new_learning = project_ledger.import_learning(global_ledger, apply)

        if new_learning:
            console.print(f"[green]Imported learning to project ledger[/green]")
            console.print(f"  Original ID: {apply[:8]}...")
            console.print(f"  New ID: {new_learning.id[:8]}")
            console.print(f"  Category: {new_learning.category.value}")
            console.print(f"  Confidence: {new_learning.confidence*100:.0f}%")
            console.print(f"\n[bold]Content:[/bold]\n{new_learning.content[:300]}...")
        else:
            console.print(f"[yellow]Could not import learning {apply[:8]}[/yellow]")
            console.print("  (It may already exist in the project ledger or not found)")
        return

    # Show suggestions
    recommender = LearningRecommender(global_ledger)

    console.print(f"[bold]Analyzing project:[/bold] {project}")

    # Get project analysis
    analysis = recommender.analyze_project(project)

    console.print(f"[dim]Type: {analysis.project_type or 'unknown'}[/dim]")
    if analysis.tech_stack:
        console.print(f"[dim]Tech stack: {', '.join(analysis.tech_stack[:5])}[/dim]")
    console.print("")

    # Get suggestions
    suggestions = recommender.get_suggestions_for_analysis(
        analysis,
        limit=limit,
        min_confidence=min_confidence,
    )

    if not suggestions:
        console.print("[dim]No relevant suggestions found in global ledger[/dim]")
        console.print("[dim]Try lowering --min-confidence or adding more learnings[/dim]")
        return

    console.print(f"[bold]Suggested learnings from global knowledge:[/bold]\n")

    for i, suggestion in enumerate(suggestions, 1):
        learning = suggestion.learning
        panel_content = []

        # Header info
        panel_content.append(f"[bold]ID:[/bold] {learning.id[:8]}")
        panel_content.append(f"[bold]Category:[/bold] {learning.category.value}")
        panel_content.append(f"[bold]Confidence:[/bold] {learning.confidence*100:.0f}%")
        panel_content.append(f"[bold]Relevance:[/bold] {suggestion.relevance_score*100:.0f}%")

        # Match reasons
        if suggestion.match_reasons:
            panel_content.append(f"[bold]Matched:[/bold] {', '.join(suggestion.match_reasons[:3])}")

        # Content preview
        content = learning.content
        if len(content) > 300:
            content = content[:300] + "..."
        panel_content.append(f"\n[bold]Content:[/bold]\n{content}")

        # Derived from info
        if learning.derived_from:
            panel_content.append(f"\n[dim]Derived from: {learning.derived_from[:8]}[/dim]")

        panel = Panel(
            "\n".join(panel_content),
            title=f"Suggestion {i}",
            border_style="cyan",
        )
        console.print(panel)

    console.print(f"\n[dim]To import a suggestion: cclaude suggest --apply <id>[/dim]")


# ============================================================================
# Outcomes Commands
# ============================================================================

@main.group()
def outcomes():
    """Manage outcome recording for learnings."""
    pass


def get_session_learnings_path(project: Path) -> Path:
    """Get the path to the session learnings tracking file."""
    return project / ".claude" / "session_learnings.json"


def load_session_learnings(path: Path) -> dict:
    """Load session learnings data."""
    import json
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {"referenced_learnings": [], "last_updated": None}


def get_learnings_needing_outcomes(
    project: Optional[Path] = None,
    min_outcome_count: int = 3,
) -> list[dict]:
    """Get learnings that have been referenced but need more outcome feedback.

    Args:
        project: Project directory (None for global only)
        min_outcome_count: Threshold below which a learning "needs" more outcomes

    Returns:
        List of learning info dicts
    """
    import json

    results = []
    seen_ids = set()

    # Determine which ledgers to check
    ledger_paths = []
    if project:
        project = project.resolve()
        ledger_paths.append(project / ".claude" / "ledger")

        # Also check session learnings for recently referenced
        session_path = get_session_learnings_path(project)
        session_data = load_session_learnings(session_path)
        recently_referenced = set(session_data.get("referenced_learnings", []))
    else:
        recently_referenced = set()

    # Always include global ledger
    ledger_paths.append(Path.home() / ".claude" / "ledger")

    for ledger_path in ledger_paths:
        reinforcements_file = ledger_path / "reinforcements.json"
        if not reinforcements_file.exists():
            continue

        try:
            with open(reinforcements_file) as f:
                data = json.load(f)
                learnings = data.get("learnings", {})

            for lid, info in learnings.items():
                lid_prefix = lid[:8].lower()

                # Skip if already processed
                if lid_prefix in seen_ids:
                    continue
                seen_ids.add(lid_prefix)

                outcome_count = info.get("outcome_count", 0)

                # Include if:
                # 1. Recently referenced in session, OR
                # 2. Has low outcome count
                is_recently_referenced = lid_prefix in recently_referenced
                needs_more_outcomes = outcome_count < min_outcome_count

                if is_recently_referenced or needs_more_outcomes:
                    # Get content from blocks
                    content = _get_learning_content_for_outcomes(ledger_path, lid)

                    results.append({
                        "id": lid_prefix,
                        "full_id": lid,
                        "category": info.get("category", "unknown"),
                        "confidence": info.get("confidence", 0.5),
                        "outcome_count": outcome_count,
                        "last_updated": info.get("last_updated"),
                        "recently_referenced": is_recently_referenced,
                        "content": content[:150] if content else "No content found",
                        "ledger": "project" if ledger_path != Path.home() / ".claude" / "ledger" else "global",
                    })

        except (json.JSONDecodeError, IOError):
            continue

    # Sort: recently referenced first, then by outcome_count ascending
    results.sort(key=lambda x: (not x["recently_referenced"], x["outcome_count"]))

    return results


def _get_learning_content_for_outcomes(ledger_path: Path, learning_id: str) -> Optional[str]:
    """Get learning content by searching blocks."""
    import json

    blocks_dir = ledger_path / "blocks"
    if not blocks_dir.exists():
        return None

    for block_file in blocks_dir.glob("*.json"):
        try:
            with open(block_file) as f:
                block = json.load(f)
            for learning in block.get("learnings", []):
                if learning.get("id") == learning_id:
                    return learning.get("content")
        except (json.JSONDecodeError, IOError):
            continue

    return None


@outcomes.command("pending")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
@click.option(
    "--all", "-a", "show_all",
    is_flag=True,
    default=False,
    help="Show all learnings needing outcomes (not just recently referenced)",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=20,
    help="Maximum results to show (default: 20)",
)
def outcomes_pending(project: Path, show_all: bool, limit: int):
    """List learnings that need outcome feedback.

    Shows learnings that were referenced in recent sessions but haven't
    received enough outcome feedback to build reliable confidence scores.
    """
    project = project.resolve()

    learnings = get_learnings_needing_outcomes(project)

    if not show_all:
        # Filter to only recently referenced
        learnings = [l for l in learnings if l.get("recently_referenced")]

    if not learnings:
        if show_all:
            console.print("[dim]No learnings found needing outcomes[/dim]")
        else:
            console.print("[dim]No recently referenced learnings need outcomes[/dim]")
            console.print("[dim]Use --all to show all learnings with low outcome counts[/dim]")
        return

    learnings = learnings[:limit]

    table = Table(title=f"Learnings Needing Outcomes ({len(learnings)})")
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Cat", style="dim", width=10)
    table.add_column("Conf", style="green", width=5)
    table.add_column("Out#", style="yellow", width=4)
    table.add_column("Recent", style="magenta", width=6)
    table.add_column("Content", style="white")

    for l in learnings:
        conf_pct = f"{int(l['confidence']*100)}%"
        recent = "Yes" if l.get("recently_referenced") else ""
        content = l["content"][:60] + "..." if len(l["content"]) > 60 else l["content"]

        table.add_row(
            l["id"],
            l["category"],
            conf_pct,
            str(l["outcome_count"]),
            recent,
            content,
        )

    console.print(table)

    console.print("\n[bold]To record an outcome:[/bold]")
    console.print("  uv run cclaude outcome <ID> -r <success|partial|failure> -c \"description\"")
    console.print("\n[bold]For batch recording:[/bold]")
    console.print("  uv run cclaude outcomes batch")


@outcomes.command("batch")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory)",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=10,
    help="Maximum learnings to process (default: 10)",
)
def outcomes_batch(project: Path, limit: int):
    """Interactive mode to record outcomes for multiple learnings.

    Walks through learnings that need outcomes and prompts for feedback.
    """
    from .ledger.models import OutcomeResult

    project = project.resolve()

    learnings = get_learnings_needing_outcomes(project)
    if not learnings:
        console.print("[dim]No learnings found needing outcomes[/dim]")
        return

    learnings = learnings[:limit]

    console.print(Panel(
        "[bold]Batch Outcome Recording[/bold]\n\n"
        f"You will be prompted for {len(learnings)} learnings.\n"
        "For each, enter: [green]s[/green]uccess, [yellow]p[/yellow]artial, [red]f[/red]ailure, or [dim]skip[/dim]\n\n"
        "Press Ctrl+C to exit at any time.",
        title="Outcome Recording",
        border_style="blue",
    ))

    recorded = 0
    skipped = 0

    for i, learning in enumerate(learnings, 1):
        console.print(f"\n[bold]({i}/{len(learnings)})[/bold] Learning: [cyan]{learning['id']}[/cyan]")
        console.print(f"  Category: {learning['category']}")
        console.print(f"  Confidence: {int(learning['confidence']*100)}%")
        console.print(f"  Outcomes so far: {learning['outcome_count']}")
        console.print(f"  Content: {learning['content']}")
        console.print()

        try:
            result_input = click.prompt(
                "Result (s/p/f/skip)",
                type=str,
                default="skip",
            ).lower().strip()

            if result_input in ("skip", ""):
                skipped += 1
                console.print("[dim]Skipped[/dim]")
                continue

            result_map = {
                "s": "success",
                "success": "success",
                "p": "partial",
                "partial": "partial",
                "f": "failure",
                "failure": "failure",
            }

            if result_input not in result_map:
                console.print("[yellow]Invalid result, skipping[/yellow]")
                skipped += 1
                continue

            result = result_map[result_input]

            context = click.prompt(
                "Context (brief description)",
                type=str,
                default="Applied in session",
            )

            # Record the outcome
            # Determine which ledger to use
            if learning["ledger"] == "project":
                ledger = get_project_ledger(project)
            else:
                ledger = get_global_ledger()

            # Find and update the learning
            found = False
            for block in ledger.get_all_blocks():
                for learn_obj in block.learnings:
                    if learn_obj.id.startswith(learning["id"]):
                        result_enum = OutcomeResult(result)
                        learn_obj.apply_outcome(result_enum, context)

                        # Update the block file
                        block_file = ledger.blocks_dir / f"{block.id}.json"
                        ledger._write_json(block_file, block.model_dump(mode="json"))

                        # Update reinforcements
                        ledger.update_learning_confidence(learn_obj.id, learn_obj.confidence)

                        console.print(f"[green]Recorded {result} -> new confidence: {int(learn_obj.confidence*100)}%[/green]")
                        recorded += 1
                        found = True
                        break
                if found:
                    break

            if not found:
                console.print(f"[red]Learning {learning['id']} not found in ledger[/red]")
                skipped += 1

        except click.Abort:
            console.print("\n[yellow]Aborted[/yellow]")
            break
        except KeyboardInterrupt:
            console.print("\n[yellow]Aborted[/yellow]")
            break

    console.print(f"\n[bold]Summary:[/bold] Recorded {recorded}, Skipped {skipped}")


# ============================================================================
# Analyze Commands (Braintrust-like session analysis)
# ============================================================================

@main.group()
def analyze():
    """LLM-powered session analysis (Braintrust-like insights)."""
    pass


@analyze.command("session")
@click.argument("transcript_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--session-id", "-s",
    type=str,
    default=None,
    help="Session ID (default: derived from filename)",
)
@click.option(
    "--no-llm",
    is_flag=True,
    help="Use regex-only extraction (faster, less accurate)",
)
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory for saving insights",
)
@click.option(
    "--save-learnings",
    is_flag=True,
    help="Also save extracted insights as learnings to the ledger",
)
def analyze_session_cmd(
    transcript_path: Path,
    session_id: Optional[str],
    no_llm: bool,
    project: Optional[Path],
    save_learnings: bool,
):
    """Analyze a session transcript and extract structured insights.

    Provides Braintrust-like learning extraction:
    - What Worked: Successful approaches and decisions
    - What Failed: Errors, dead ends, incorrect assumptions
    - Patterns: Reusable solutions and workflows
    - Key Decisions: Important choices made during the session
    """
    try:
        from .analysis import TranscriptAnalyzer, SessionInsights
        from .analysis.transcript import save_insights
    except ImportError:
        console.print("[red]Analysis module not available[/red]")
        return

    # Derive session ID from filename if not provided
    if not session_id:
        session_id = transcript_path.stem

    console.print(f"[bold]Analyzing session:[/bold] {session_id}")
    console.print(f"[dim]Transcript: {transcript_path}[/dim]")
    console.print(f"[dim]Using LLM: {not no_llm}[/dim]\n")

    # Create analyzer and run
    analyzer = TranscriptAnalyzer(use_llm=not no_llm)
    insights = analyzer.analyze_from_file(transcript_path, session_id)

    # Display results
    console.print(Panel(insights.summary or "No summary generated", title="Summary"))

    if insights.what_worked:
        console.print("\n[bold green]What Worked[/bold green]")
        for item in insights.what_worked:
            console.print(f"  • {item}")

    if insights.what_failed:
        console.print("\n[bold red]What Failed[/bold red]")
        for item in insights.what_failed:
            console.print(f"  • {item}")

    if insights.patterns:
        console.print("\n[bold blue]Patterns Identified[/bold blue]")
        for item in insights.patterns:
            console.print(f"  • {item}")

    if insights.key_decisions:
        console.print("\n[bold yellow]Key Decisions[/bold yellow]")
        for item in insights.key_decisions:
            console.print(f"  • {item}")

    if insights.metrics:
        console.print("\n[bold]Metrics[/bold]")
        console.print(f"  Duration: {insights.metrics.duration_seconds:.1f}s")
        console.print(f"  Turns: {insights.metrics.turn_count}")
        console.print(f"  Tool calls: {insights.metrics.tool_call_count}")
        console.print(f"  Success rate: {insights.metrics.overall_success_rate:.1f}%")

        patterns = insights.metrics.get_frequent_patterns()
        if patterns:
            console.print("\n  [dim]Frequent Tool Patterns:[/dim]")
            for pattern, count in patterns[:5]:
                console.print(f"    {pattern} ({count}x)")

    # Save insights
    if project:
        project = project.resolve()
        insights_dir = project / ".claude" / "insights" / session_id
        save_insights(insights, insights_dir)
        console.print(f"\n[green]Insights saved to {insights_dir}[/green]")

    # Save as learnings if requested
    if save_learnings:
        learnings = insights.to_learnings()
        if learnings:
            ledger = get_project_ledger(project) if project else get_global_ledger()
            block = ledger.create_block(f"analysis-{session_id}")
            for learning in learnings:
                block.add_learning(
                    category=LearningCategory(learning["category"]),
                    content=learning["content"],
                    source=learning.get("source"),
                    confidence=learning.get("confidence", 0.5),
                )
            ledger.append_block(block)
            console.print(f"[green]Saved {len(learnings)} learnings to ledger[/green]")


@analyze.command("metrics")
@click.option(
    "--project", "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=10,
    help="Number of recent sessions to analyze",
)
def analyze_metrics(project: Path, limit: int):
    """Show aggregated metrics across recent sessions."""
    project = project.resolve()
    insights_dir = project / ".claude" / "insights"

    if not insights_dir.exists():
        console.print("[yellow]No insights found. Run 'cclaude analyze session' first.[/yellow]")
        return

    import json

    # Collect all insights
    all_insights = []
    for session_dir in sorted(insights_dir.iterdir(), reverse=True)[:limit]:
        if not session_dir.is_dir():
            continue
        for insight_file in session_dir.glob("insights-*.json"):
            try:
                with open(insight_file) as f:
                    data = json.load(f)
                    all_insights.append(data)
            except (json.JSONDecodeError, IOError):
                continue

    if not all_insights:
        console.print("[yellow]No insights data found.[/yellow]")
        return

    # Aggregate metrics
    total_duration = 0
    total_turns = 0
    total_tool_calls = 0
    total_errors = 0
    tool_usage = {}
    all_patterns = []
    all_failures = []

    for insight in all_insights:
        metrics = insight.get("metrics", {})
        total_duration += metrics.get("duration_seconds", 0)
        total_turns += metrics.get("turn_count", 0)
        total_tool_calls += metrics.get("tool_call_count", 0)
        total_errors += metrics.get("error_count", 0)

        for tool, info in metrics.get("tool_metrics", {}).items():
            if tool not in tool_usage:
                tool_usage[tool] = {"calls": 0, "errors": 0}
            tool_usage[tool]["calls"] += info.get("call_count", 0)
            tool_usage[tool]["errors"] += info.get("call_count", 0) - int(
                info.get("call_count", 0) * info.get("success_rate", 100) / 100
            )

        all_patterns.extend(insight.get("patterns", []))
        all_failures.extend(insight.get("what_failed", []))

    # Display aggregated metrics
    console.print(f"[bold]Session Analysis Summary[/bold] ({len(all_insights)} sessions)\n")

    console.print(f"Total duration: {total_duration / 60:.1f} minutes")
    console.print(f"Total turns: {total_turns}")
    console.print(f"Total tool calls: {total_tool_calls}")
    console.print(f"Overall success rate: {((total_tool_calls - total_errors) / max(total_tool_calls, 1)) * 100:.1f}%")

    if tool_usage:
        console.print("\n[bold]Tool Usage[/bold]")
        table = Table()
        table.add_column("Tool")
        table.add_column("Calls", justify="right")
        table.add_column("Errors", justify="right")
        table.add_column("Success %", justify="right")

        for tool, info in sorted(tool_usage.items(), key=lambda x: x[1]["calls"], reverse=True)[:10]:
            success_rate = ((info["calls"] - info["errors"]) / max(info["calls"], 1)) * 100
            table.add_row(
                tool,
                str(info["calls"]),
                str(info["errors"]),
                f"{success_rate:.0f}%",
            )
        console.print(table)

    # Common patterns
    if all_patterns:
        console.print("\n[bold]Common Patterns[/bold]")
        from collections import Counter
        pattern_counts = Counter(all_patterns)
        for pattern, count in pattern_counts.most_common(5):
            console.print(f"  ({count}x) {pattern[:80]}...")

    # Common failures
    if all_failures:
        console.print("\n[bold]Common Failures[/bold]")
        from collections import Counter
        failure_counts = Counter(all_failures)
        for failure, count in failure_counts.most_common(5):
            console.print(f"  ({count}x) {failure[:80]}...")


if __name__ == "__main__":
    main()
