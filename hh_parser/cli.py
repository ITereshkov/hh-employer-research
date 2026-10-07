import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

import click
from rich.console import Console
from rich.table import Table

from .config import AppConfig
from .db.connection import DatabaseConnection
from .db.schema import run_migrations
from .db.repositories import (
    EmployerRepository,
    VacancyRepository,
    EmployerVacancyRepository,
    ContactRepository,
    SearchRunRepository,
    EmployerFilters,
)
from .api.rate_limiter import RateLimiter
from .api.client import HHApiClient
from .search.searcher import VacancySearcher
from .search.employer_extractor import EmployerExtractor
from .search.keywords import build_search_queries

console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _get_components(config: AppConfig):
    db = DatabaseConnection(config.database.path)
    conn = db.connect()
    run_migrations(conn)
    return conn, db


@click.group()
@click.option("--config", "-c", type=click.Path(exists=True), help="Config file path")
@click.option("--verbose", "-v", is_flag=True, help="Debug logging")
@click.pass_context
def cli(ctx, config, verbose):
    """HH.ru Employer Research Parser."""
    ctx.ensure_object(dict)
    cfg = AppConfig.load(Path(config) if config else None)
    if verbose:
        cfg.log_level = "DEBUG"
    _setup_logging(cfg.log_level)
    ctx.obj["config"] = cfg


@cli.command()
@click.option("--area", "-a", type=int, default=None, help="Area ID filter")
@click.option("--max-pages", "-m", type=int, default=None, help="Max pages per keyword")
@click.option("--keywords", "-k", type=str, multiple=True, help="Custom keywords")
@click.pass_context
def search(ctx, area, max_pages, keywords):
    """Run vacancy search."""
    config = ctx.obj["config"]
    conn, db = _get_components(config)

    if max_pages:
        config.search.max_pages = max_pages

    cache_dir = config.data_dir / "cache"
    limiter = RateLimiter(
        per_minute=config.rate_limit.requests_per_minute,
        per_day=config.rate_limit.requests_per_day,
    )
    api = HHApiClient(limiter, cache_dir=cache_dir, max_retries=config.rate_limit.max_retries)

    run_repo = SearchRunRepository(conn)
    run_id = run_repo.create_run(
        ", ".join(keywords) if keywords else "all_keywords", area
    )

    try:
        searcher = VacancySearcher(api, config.search)
        result = asyncio.run(searcher.run_search(area=area, custom_keywords=list(keywords) if keywords else None))
        result.search_run_id = run_id

        employer_repo = EmployerRepository(conn)
        vacancy_repo = VacancyRepository(conn)
        ev_repo = EmployerVacancyRepository(conn)
        extractor = EmployerExtractor(employer_repo, vacancy_repo, ev_repo, api)

        extracted = asyncio.run(extractor.extract_from_vacancies(result.collected_vacancies))
        result.new_employers = sum(1 for e in extracted if e.is_new)
        result.new_vacancies = result.total_vacancies_found

        run_repo.complete_run(
            run_id,
            result.total_vacancies_found,
            config.search.max_pages,
            result.new_employers,
            result.new_vacancies,
        )

        console.print(f"\n[green]Search complete.[/green]")
        console.print(f"  Vacancies found: {result.total_vacancies_found}")
        console.print(f"  New employers:   {result.new_employers}")
        console.print(f"  Total employers: {employer_repo.count()}")

        if result.errors:
            console.print(f"\n[yellow]Errors ({len(result.errors)}):[/yellow]")
            for err in result.errors[:5]:
                console.print(f"  - {err}")

    except Exception as e:
        run_repo.fail_run(run_id, str(e))
        console.print(f"[red]Search failed: {e}[/red]")
        raise
    finally:
        asyncio.run(api.close())
        conn.close()


@cli.command()
@click.option("--employer-id", "-e", type=int, help="Fetch specific employer")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch all employers")
@click.option("--limit", "-l", type=int, default=100, help="Max employers to fetch")
@click.pass_context
def fetch_employers(ctx, employer_id, fetch_all, limit):
    """Fetch full employer details from HH.ru."""
    config = ctx.obj["config"]
    conn, db = _get_components(config)

    cache_dir = config.data_dir / "cache"
    limiter = RateLimiter(
        per_minute=config.rate_limit.requests_per_minute,
        per_day=config.rate_limit.requests_per_day,
    )
    api = HHApiClient(limiter, cache_dir=cache_dir)
    employer_repo = EmployerRepository(conn)
    extractor = EmployerExtractor(employer_repo, None, None, api)

    try:
        if employer_id:
            ids = [employer_id]
        elif fetch_all:
            ids = employer_repo.get_all_employer_ids()[:limit]
        else:
            console.print("[red]Specify --employer-id or --all[/red]")
            return

        console.print(f"Fetching {len(ids)} employer(s)...")
        results = asyncio.run(extractor.fetch_full_details(ids))
        console.print(f"[green]Fetched {len(results)} employer(s).[/green]")
    finally:
        asyncio.run(api.close())
        conn.close()


@cli.command()
@click.option("--output", "-o", type=click.Path(), default=None)
@click.option("--region", type=str, default=None, help="Filter by region name")
@click.option("--min-score", type=float, default=None)
@click.pass_context
def export(ctx, output, region, min_score):
    """Export employer data to XLSX."""
    config = ctx.obj["config"]
    conn, db = _get_components(config)

    from .export.xlsx import XLSXExporter

    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = str(config.reports_dir / f"employers_{timestamp}.xlsx")

    filters = EmployerFilters()
    if min_score is not None:
        filters.min_signal_score = min_score

    employer_repo = EmployerRepository(conn)
    vacancy_repo = VacancyRepository(conn)
    exporter = XLSXExporter(employer_repo, vacancy_repo)
    path = exporter.export(Path(output), filters=filters)
    console.print(f"[green]Exported to {path}[/green]")
    conn.close()


@cli.command()
@click.pass_context
def stats(ctx):
    """Show database statistics."""
    config = ctx.obj["config"]
    conn, db = _get_components(config)

    employer_repo = EmployerRepository(conn)
    vacancy_repo = VacancyRepository(conn)

    total_employers = employer_repo.count()
    total_vacancies = vacancy_repo.count_active()
    enriched = employer_repo.count(EmployerFilters(enrichment_status="done"))
    pending = employer_repo.count(EmployerFilters(enrichment_status="pending"))

    categories = vacancy_repo.count_by_category()
    fresh_7 = vacancy_repo.count_fresh(7)
    fresh_30 = vacancy_repo.count_fresh(30)

    table = Table(title="HH Employer Research — Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Total employers", str(total_employers))
    table.add_row("Active vacancies", str(total_vacancies))
    table.add_row("Enriched", str(enriched))
    table.add_row("Pending enrichment", str(pending))
    table.add_row("Fresh (7 days)", str(fresh_7))
    table.add_row("Fresh (30 days)", str(fresh_30))
    table.add_row("", "")
    for cat, count in sorted(categories.items()):
        table.add_row(f"  {cat}", str(count))

    console.print(table)
    conn.close()


@cli.command()
@click.pass_context
def init_db(ctx):
    """Initialize database schema."""
    config = ctx.obj["config"]
    conn, db = _get_components(config)
    console.print(f"[green]Database initialized at {config.database.path}[/green]")
    conn.close()


@cli.command()
@click.pass_context
def areas(ctx):
    """List HH.ru areas (top-level regions)."""
    config = ctx.obj["config"]
    limiter = RateLimiter()
    api = HHApiClient(limiter)
    try:
        areas_data = asyncio.run(api.get_areas())
        table = Table(title="HH.ru Areas (Russia)")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        for a in areas_data:
            if a.get("id") == 113:
                for child in a.get("areas", []):
                    table.add_row(str(child["id"]), child["name"])
                break
        console.print(table)
    finally:
        asyncio.run(api.close())


@cli.command()
@click.pass_context
def keywords(ctx):
    """Show configured search keywords."""
    table = Table(title="Search Keywords")
    table.add_column("Category", style="cyan")
    table.add_column("Term", style="green")
    for term, category in build_search_queries():
        table.add_row(category.value, term)
    console.print(table)


@cli.command()
@click.option("--batch-size", "-b", type=int, default=50)
@click.option("--limit", "-l", type=int, default=100)
@click.option("--force", is_flag=True, help="Re-enrich even if TTL not expired")
@click.pass_context
def enrich(ctx, batch_size, limit, force):
    """Run contact enrichment pipeline."""
    config = ctx.obj["config"]
    conn, db = _get_components(config)

    from .enrichment.pipeline import EnrichmentPipeline

    employer_repo = EmployerRepository(conn)
    contact_repo = ContactRepository(conn)

    pipeline = EnrichmentPipeline(config.enrichment, employer_repo, contact_repo, conn)

    try:
        result = asyncio.run(pipeline.enrich_batch(limit=limit))
        console.print(f"\n[green]Enrichment complete.[/green]")
        console.print(f"  Processed:  {result['total_processed']}")
        console.print(f"  Successful: {result['successful']}")
        console.print(f"  Failed:     {result['failed']}")
        console.print(f"  Contacts:   {result['contacts_found']}")
        console.print(f"  Duration:   {result['duration_seconds']:.1f}s")
    finally:
        conn.close()


@cli.command()
@click.argument("employer_id", type=int)
@click.pass_context
def enrich_one(ctx, employer_id):
    """Enrich a single employer."""
    config = ctx.obj["config"]
    conn, db = _get_components(config)

    from .enrichment.pipeline import EnrichmentPipeline

    employer_repo = EmployerRepository(conn)
    contact_repo = ContactRepository(conn)
    pipeline = EnrichmentPipeline(config.enrichment, employer_repo, contact_repo, conn)

    try:
        result = asyncio.run(pipeline.enrich_single(employer_id))
        if result["success"]:
            console.print(f"[green]Enriched employer {employer_id}[/green]")
            for c in result.get("contacts", []):
                console.print(f"  {c['contact_type']}: {c['value']} (src: {c['source_type']}, conf: {c['confidence']})")
        else:
            console.print(f"[red]Failed: {result.get('error')}[/red]")
    finally:
        conn.close()


def main():
    cli()
