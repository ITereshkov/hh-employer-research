"""CLI entry point for hh_research."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import ResearchConfig
from .pipeline import ResearchPipeline
from .storage import Storage


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_collect(args):
    config = ResearchConfig.load(args.config)
    if args.area:
        config.areas.ids = [int(a) for a in args.area]
    pipeline = ResearchPipeline(config)
    try:
        summary = pipeline.run()
        if args.export:
            formats = [f.strip() for f in args.export.split(",")]
            paths = pipeline.export_all(formats)
            print("\nExported:")
            for fmt, path in paths.items():
                print(f"  {fmt}: {path}")
        print("\nSummary:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    finally:
        pipeline.close()


def cmd_export(args):
    config = ResearchConfig.load(args.config)
    storage = Storage(config.storage.db_path)
    snapshot_id = args.snapshot or storage.get_latest_snapshot_id()
    if not snapshot_id:
        print("No snapshots found.")
        sys.exit(1)

    from .aggregation import EmployerRecord, RelevantVacancyRecord, SignalMetrics, compute_signal_metrics

    all_emps = storage.get_all_employers(snapshot_id)
    relevant_vacs = storage.get_relevant_vacancies(snapshot_id)

    vac_by_emp: dict[int, list[dict]] = {}
    for v in relevant_vacs:
        vac_by_emp.setdefault(v["employer_id"], []).append(v)

    records = []
    metrics: dict[int, SignalMetrics] = {}
    for emp in all_emps:
        emp_vacs = vac_by_emp.get(emp["id"], [])
        rel_records = []
        for v in emp_vacs:
            matched_terms = json.loads(v.get("matched_terms", "[]"))
            rel_records.append(RelevantVacancyRecord(
                vacancy_id=v["id"],
                vacancy_name=v["name"],
                vacancy_url=v.get("url"),
                published_at=v.get("published_at"),
                salary_from=v.get("salary_from"),
                salary_to=v.get("salary_to"),
                currency=v.get("currency"),
                schedule=v.get("schedule"),
                employment=v.get("employment"),
                experience=v.get("experience"),
                matched_terms=matched_terms,
                match_reason=v.get("match_reason", ""),
                relevance_score=v.get("relevance_score", 0.0),
            ))
        from .employer_classifier import ClassificationResult, EmployerType
        try:
            etype = EmployerType(emp.get("classification", "UNKNOWN"))
        except ValueError:
            etype = EmployerType.UNKNOWN
        classification = ClassificationResult(
            etype,
            emp.get("classification_confidence", 0.0),
            emp.get("classification_reason", ""),
        )
        record = build_record_from_db(emp, rel_records, classification)
        records.append(record)
        metrics[emp["id"]] = compute_signal_metrics(record)

    formats = [f.strip() for f in args.format.split(",")]
    paths = {}
    summary = {
        "snapshot_id": snapshot_id,
        "employers_total": len(records),
        "employers_with_relevant": sum(1 for r in records if r.relevant_open_vacancies > 0),
        "relevant_vacancies_total": sum(r.relevant_open_vacancies for r in records),
    }
    from .export import export_csv, export_json, export_xlsx
    if "csv" in formats:
        emp_path, vac_path = export_csv(records, metrics, config.export_dir)
        paths["csv_employers"] = emp_path
        paths["csv_vacancies"] = vac_path
    if "xlsx" in formats:
        paths["xlsx"] = export_xlsx(records, metrics, config.export_dir, summary)
    if "json" in formats:
        paths["json"] = export_json(records, metrics, config.export_dir)

    print("Exported:")
    for fmt, path in paths.items():
        print(f"  {fmt}: {path}")
    storage.close()


def build_record_from_db(emp: dict, rel_vacs, classification):
    from .aggregation import EmployerRecord, RelevantVacancyRecord
    rec = EmployerRecord(
        snapshot_at=emp.get("last_seen_at", ""),
        employer_id=emp["id"],
        employer_name=emp["name"],
        employer_type=classification.employer_type.value,
        employer_type_confidence=classification.confidence,
        classification_reason=classification.reason,
        employer_hh_url=emp.get("url"),
        employer_site_url=None,
        area_id=emp.get("area_id"),
        area_name=emp.get("area_name"),
        industry=emp.get("industry"),
        total_open_vacancies=emp.get("total_open_vacancies", 0),
        relevant_open_vacancies=len(rel_vacs),
        relevant_vacancies=rel_vacs,
    )
    return rec


def cmd_stats(args):
    config = ResearchConfig.load(args.config)
    storage = Storage(config.storage.db_path)
    snapshot_id = args.snapshot or storage.get_latest_snapshot_id()
    if not snapshot_id:
        print("No snapshots found.")
        sys.exit(1)

    info = storage.get_snapshot_info(snapshot_id)
    print(f"Snapshot {snapshot_id}: {info}")

    all_emps = storage.get_all_employers(snapshot_id)
    relevant_vacs = storage.get_relevant_vacancies(snapshot_id)

    with_relevant = [e for e in all_emps if e.get("relevant_open_vacancies", 0) > 0]

    print(f"\nEmployers total: {len(all_emps)}")
    print(f"Employers with relevant vacancies: {len(with_relevant)}")
    print(f"Relevant vacancies: {len(relevant_vacs)}")

    by_type: dict[str, int] = {}
    for e in all_emps:
        t = e.get("classification", "UNKNOWN")
        by_type[t] = by_type.get(t, 0) + 1
    print("\nBy employer type:")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")

    by_area: dict[str, int] = {}
    for e in all_emps:
        a = e.get("area_name", "Unknown")
        by_area[a] = by_area.get(a, 0) + 1
    print("\nBy area:")
    for a, c in sorted(by_area.items(), key=lambda x: -x[1])[:15]:
        print(f"  {a}: {c}")

    if with_relevant:
        print("\nTop employers by relevant vacancies:")
        for e in sorted(with_relevant, key=lambda x: -x.get("relevant_open_vacancies", 0))[:10]:
            print(f"  [{e['id']}] {e['name']} — {e['relevant_open_vacancies']} relevant")

    storage.close()


def cmd_employer(args):
    config = ResearchConfig.load(args.config)
    storage = Storage(config.storage.db_path)
    snapshot_id = args.snapshot or storage.get_latest_snapshot_id()
    if not snapshot_id:
        print("No snapshots found.")
        sys.exit(1)

    all_emps = storage.get_all_employers(snapshot_id)
    emp = next((e for e in all_emps if e["id"] == args.employer_id), None)
    if not emp:
        print(f"Employer {args.employer_id} not found in snapshot {snapshot_id}")
        sys.exit(1)

    print(f"Employer: {emp['name']} (ID: {emp['id']})")
    print(f"Type: {emp.get('classification')} (confidence: {emp.get('classification_confidence')})")
    print(f"Reason: {emp.get('classification_reason')}")
    print(f"Area: {emp.get('area_name')}")
    print(f"Industry: {emp.get('industry')}")
    print(f"Total vacancies: {emp.get('total_open_vacancies')}")
    print(f"Relevant vacancies: {emp.get('relevant_open_vacancies')}")
    print(f"URL: {emp.get('url')}")
    print(f"Enrichment: {emp.get('enrichment_status') or 'pending'}")
    if emp.get('official_website'):
        print(f"Website: {emp['official_website']}")
    if emp.get('official_phone'):
        print(f"Phone: {emp['official_phone']}")
    if emp.get('official_email'):
        print(f"Email: {emp['official_email']}")
    if emp.get('facility_contact_phone'):
        print(f"Facility phone: {emp['facility_contact_phone']}")

    vacs = storage.get_relevant_vacancies(snapshot_id)
    emp_vacs = [v for v in vacs if v["employer_id"] == args.employer_id]
    if emp_vacs:
        print(f"\nRelevant vacancies:")
        for v in emp_vacs:
            print(f"  [{v['id']}] {v['name']} (score: {v.get('relevance_score', 0):.2f})")
            print(f"    URL: {v.get('url')}")
            print(f"    Terms: {v.get('matched_terms')}")
            print(f"    Reason: {v.get('match_reason')}")

    contacts = storage.get_contacts(args.employer_id)
    if contacts:
        print(f"\nContacts ({len(contacts)}):")
        for c in contacts:
            fac = " [АХО]" if c.get("is_facility") else ""
            pri = " [primary]" if c.get("is_primary") else ""
            print(f"  {c['contact_type']}: {c['value']} (conf: {c.get('confidence', 0):.2f}, src: {c.get('source_type', '')}){fac}{pri}")

    storage.close()


def cmd_enrich(args):
    config = ResearchConfig.load(args.config)
    from .api_client import HHApiClient
    from .enrichment.pipeline import EnrichmentPipeline

    api = HHApiClient(config.api, config.storage)
    storage = Storage(config.storage.db_path)
    pipeline = EnrichmentPipeline(api, storage, ttl_hours=args.ttl)

    if args.employer_id:
        result = pipeline.enrich_single(args.employer_id)
        print(f"Enrichment result: {json.dumps(result, ensure_ascii=False, indent=2)}")
    else:
        result = pipeline.enrich_batch(limit=args.limit)
        print(f"\nEnrichment batch complete:")
        for k, v in result.items():
            print(f"  {k}: {v}")

    storage.commit()
    storage.close()


def cmd_enrichment_stats(args):
    config = ResearchConfig.load(args.config)
    storage = Storage(config.storage.db_path)
    stats = storage.get_enrichment_stats()
    print("Enrichment statistics:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    storage.close()


def cmd_collect_cleaning(args):
    from .cleaning_signal.config import CleaningSignalConfig
    from .cleaning_signal.pipeline import CleaningSignalPipeline

    config = CleaningSignalConfig.load(args.config)
    pipeline = CleaningSignalPipeline(config)
    try:
        summary = pipeline.run()
        print("\nSummary:")
        for k, v in summary.items():
            if k == "top_employers":
                print(f"  {k}:")
                for emp in v:
                    print(
                        f"    [{emp['employer_id']}] {emp['employer_name']} "
                        f"score={emp['signal_score']:.1f} ({emp['signal_level']}) "
                        f"vacancies={emp['relevant_count']}"
                    )
            else:
                print(f"  {k}: {v}")
    finally:
        pipeline.close()


def cmd_rank_cleaning(args):
    from .cleaning_signal.config import CleaningSignalConfig

    config = CleaningSignalConfig.load(args.config)
    storage = Storage(config.storage.db_path)
    snapshot_id = args.snapshot or storage.get_latest_snapshot_id()
    if not snapshot_id:
        print("No snapshots found.")
        sys.exit(1)

    info = storage.get_snapshot_info(snapshot_id)
    print(f"Snapshot {snapshot_id}: {info}")

    all_emps = storage.get_all_employers(snapshot_id)
    relevant_vacs = storage.get_relevant_vacancies(snapshot_id)

    vac_by_emp: dict[int, int] = {}
    for v in relevant_vacs:
        vac_by_emp[v["employer_id"]] = vac_by_emp.get(v["employer_id"], 0) + 1

    sorted_emps = sorted(
        all_emps,
        key=lambda e: e.get("signal_score", 0) or 0,
        reverse=True,
    )

    high = [e for e in sorted_emps if (e.get("signal_score", 0) or 0) >= 8.0]
    medium = [e for e in sorted_emps if 4.0 <= (e.get("signal_score", 0) or 0) < 8.0]
    low = [e for e in sorted_emps if (e.get("signal_score", 0) or 0) < 4.0]

    print(f"\nEmployers total: {len(all_emps)}")
    print(f"  HIGH signal: {len(high)}")
    print(f"  MEDIUM signal: {len(medium)}")
    print(f"  LOW signal: {len(low)}")
    print(f"Relevant vacancies: {len(relevant_vacs)}")

    providers = [e for e in sorted_emps if e.get("classification") == "CLEANING_COMPANY"]
    print(f"Cleaning providers (excluded from outreach): {len(providers)}")

    print("\nTop employers by signal score:")
    for e in sorted_emps[:20]:
        score = e.get("signal_score", 0) or 0
        rel = vac_by_emp.get(e["id"], 0)
        cat = e.get("classification", "OTHER")
        area = e.get("area_name", "")
        print(
            f"  [{e['id']}] {e['name']}"
            f"  score={score:.1f}  vacancies={rel}  cat={cat}  area={area}"
        )

    storage.close()


def cmd_enrich_cleaning(args):
    from .cleaning_signal.config import CleaningSignalConfig
    from .cleaning_signal.aggregation import EmployerAggregate, select_enrichment_cohort
    from .cleaning_signal.classifier import EmployerCategory
    from .api_client import HHApiClient
    from .enrichment.pipeline import EnrichmentPipeline

    config = CleaningSignalConfig.load(args.config)
    api = HHApiClient(config.api, config.storage)
    storage = Storage(config.storage.db_path)
    enrichment = EnrichmentPipeline(api, storage, ttl_hours=args.ttl)

    snapshot_id = args.snapshot or storage.get_latest_snapshot_id()
    if not snapshot_id:
        print("No snapshots found.")
        sys.exit(1)

    all_emps = storage.get_all_employers(snapshot_id)
    employers_map: dict[int, EmployerAggregate] = {}
    for emp in all_emps:
        eid = emp["id"]
        try:
            cat = EmployerCategory(emp.get("classification", "OTHER"))
        except ValueError:
            cat = EmployerCategory.OTHER
        employers_map[eid] = EmployerAggregate(
            employer_id=eid,
            employer_name=emp["name"],
            employer_hh_url=emp.get("url"),
            employer_category=cat,
            signal_score=emp.get("signal_score", 0) or 0,
        )

    cohort_ids = select_enrichment_cohort(
        employers_map,
        config.enrichment_cohort.signal_levels,
        args.limit or config.enrichment_cohort.max_employers,
        config.enrichment_cohort.min_signal_score,
        config.enrichment_cohort.include_top_medium,
    )

    print(f"Enrichment cohort: {len(cohort_ids)} employers from snapshot {snapshot_id}")

    successful = 0
    failed = 0
    for eid in cohort_ids:
        try:
            result = enrichment.enrich_single(eid)
            if result.get("success"):
                successful += 1
                contacts = result.get("contacts", [])
                print(f"  [{eid}] OK — {len(contacts)} contacts")
            else:
                failed += 1
                print(f"  [{eid}] FAILED")
        except Exception as e:
            failed += 1
            print(f"  [{eid}] ERROR: {e}")

    storage.commit()
    print(f"\nEnrichment done: {successful} ok, {failed} failed")
    storage.close()


def cmd_export_cleaning(args):
    from .cleaning_signal.config import CleaningSignalConfig
    from .cleaning_signal.aggregation import (
        EmployerAggregate,
        VacancySummary,
    )
    from .cleaning_signal.classifier import EmployerCategory, RoleCategory
    from .cleaning_signal.export import export_cleaning_xlsx

    config = CleaningSignalConfig.load(args.config)
    storage = Storage(config.storage.db_path)
    snapshot_id = args.snapshot or storage.get_latest_snapshot_id()
    if not snapshot_id:
        print("No snapshots found.")
        sys.exit(1)

    all_emps = storage.get_all_employers(snapshot_id)
    relevant_vacs = storage.get_relevant_vacancies(snapshot_id)

    vac_by_emp: dict[int, list[dict]] = {}
    for v in relevant_vacs:
        vac_by_emp.setdefault(v["employer_id"], []).append(v)

    employers: list[EmployerAggregate] = []
    for emp in all_emps:
        eid = emp["id"]
        try:
            cat = EmployerCategory(emp.get("classification", "OTHER"))
        except ValueError:
            cat = EmployerCategory.OTHER

        emp_vacs = vac_by_emp.get(eid, [])
        summaries = []
        for v in emp_vacs:
            matched_terms = json.loads(v.get("matched_terms", "[]"))
            role_cat = RoleCategory.OTHER_RELEVANT
            summaries.append(VacancySummary(
                vacancy_id=v["id"],
                name=v["name"],
                url=v.get("url"),
                published_at=v.get("published_at"),
                role_category=role_cat,
                matched_terms=matched_terms,
                relevance_score=v.get("relevance_score", 0.0),
                area_id=v.get("area_id"),
                area_name=v.get("area_name"),
                salary_from=v.get("salary_from"),
                salary_to=v.get("salary_to"),
                currency=v.get("currency"),
            ))

        area_name = emp.get("area_name", "")
        regions = [r.strip() for r in area_name.split("|")] if area_name else []

        agg = EmployerAggregate(
            employer_id=eid,
            employer_name=emp["name"],
            employer_hh_url=emp.get("url"),
            employer_category=cat,
            employer_category_reason=emp.get("classification_reason", ""),
            employer_category_confidence=emp.get("classification_confidence", 0.0),
            is_cleaning_provider=(cat == EmployerCategory.CLEANING_COMPANY),
            regions=regions,
            relevant_vacancies=summaries,
            signal_score=emp.get("signal_score", 0) or 0,
        )
        if agg.signal_score >= config.scoring.threshold_high:
            agg.signal_level = "HIGH"
        elif agg.signal_score >= config.scoring.threshold_medium:
            agg.signal_level = "MEDIUM"
        else:
            agg.signal_level = "LOW"
        employers.append(agg)

    enriched: dict[int, dict] = {}
    for emp in all_emps:
        eid = emp["id"]
        contacts = storage.get_contacts(eid)
        if contacts or emp.get("enrichment_status"):
            entry: dict = {"enrichment_status": emp.get("enrichment_status", "")}
            for c in contacts:
                ct = c.get("contact_type", "")
                val = c.get("value", "")
                if ct == "website":
                    entry["official_website"] = val
                elif ct == "phone":
                    if "official_phone" not in entry:
                        entry["official_phone"] = val
                elif ct == "email":
                    if "official_email" not in entry:
                        entry["official_email"] = val
            enriched[eid] = entry

    path = export_cleaning_xlsx(
        employers=employers,
        total_raw=len(relevant_vacs),
        total_relevant=len(relevant_vacs),
        total_rejected=0,
        export_dir=config.export_dir,
        enriched=enriched,
    )
    print(f"Exported: {path}")
    storage.close()


def cmd_dashboard(args):
    import subprocess
    dashboard_path = str(Path(__file__).parent / "dashboard" / "app.py")
    cmd = [sys.executable, "-m", "streamlit", "run", dashboard_path]
    if args.port:
        cmd.extend(["--server.port", str(args.port)])
    print(f"Starting dashboard: {' '.join(cmd)}")
    subprocess.run(cmd)


def main():
    parser = argparse.ArgumentParser(
        prog="hh-research",
        description="HH Employer Research Parser",
    )
    parser.add_argument("--config", default=None, help="Path to config YAML")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")

    p_collect = sub.add_parser("collect", help="Run data collection")
    p_collect.add_argument("--area", nargs="+", help="Override area IDs")
    p_collect.add_argument("--export", default="csv,xlsx,json", help="Export formats (comma-separated)")

    p_export = sub.add_parser("export", help="Export from existing snapshot")
    p_export.add_argument("--snapshot", type=int, help="Snapshot ID (default: latest)")
    p_export.add_argument("--format", default="csv,xlsx,json", help="Export formats")

    p_stats = sub.add_parser("stats", help="Show run statistics")
    p_stats.add_argument("--snapshot", type=int, help="Snapshot ID")

    p_emp = sub.add_parser("employer", help="Show employer details")
    p_emp.add_argument("employer_id", type=int)
    p_emp.add_argument("--snapshot", type=int, help="Snapshot ID")

    p_enrich = sub.add_parser("enrich", help="Enrich employers with contacts")
    p_enrich.add_argument("--employer-id", type=int, default=None, help="Single employer ID")
    p_enrich.add_argument("--limit", type=int, default=100, help="Max employers to enrich")
    p_enrich.add_argument("--ttl", type=float, default=24.0, help="TTL in hours")

    p_estats = sub.add_parser("enrichment-stats", help="Show enrichment statistics")

    p_dash = sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    p_dash.add_argument("--port", type=int, default=None, help="Dashboard port")

    p_cc = sub.add_parser(
        "collect-cleaning", help="Run cleaning-signal data collection",
    )
    p_cc.add_argument("--area", nargs="+", help="Override area IDs")

    p_rc = sub.add_parser(
        "rank-cleaning", help="Show ranked employers from cleaning-signal snapshot",
    )
    p_rc.add_argument("--snapshot", type=int, help="Snapshot ID (default: latest)")

    p_ec = sub.add_parser(
        "enrich-cleaning", help="Enrich high-signal employers with contacts",
    )
    p_ec.add_argument("--snapshot", type=int, help="Snapshot ID")
    p_ec.add_argument("--limit", type=int, default=None, help="Max employers to enrich")
    p_ec.add_argument("--ttl", type=float, default=24.0, help="TTL in hours")

    p_xc = sub.add_parser(
        "export-cleaning", help="Export cleaning-signal results to XLSX",
    )
    p_xc.add_argument("--snapshot", type=int, help="Snapshot ID")
    p_xc.add_argument("--format", default="xlsx", help="Export format (default: xlsx)")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command == "collect":
        cmd_collect(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "employer":
        cmd_employer(args)
    elif args.command == "enrich":
        cmd_enrich(args)
    elif args.command == "enrichment-stats":
        cmd_enrichment_stats(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    elif args.command == "collect-cleaning":
        cmd_collect_cleaning(args)
    elif args.command == "rank-cleaning":
        cmd_rank_cleaning(args)
    elif args.command == "enrich-cleaning":
        cmd_enrich_cleaning(args)
    elif args.command == "export-cleaning":
        cmd_export_cleaning(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
