"""Firewall commands — train and manage Tier 2 classifiers for hb-firewall."""

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.group("firewall")
def firewall_group():
    """Train and manage Tier 2 classifiers for hb-firewall.

    \b
    Workflow:
      1. Run adversarial tests:  hb test
      2. Train classifiers:      hb firewall train --model detectors/my_model.py
      3. Load in your app:       Firewall.from_config("agent.yaml", model_path="fw.hbfw")
    """


@firewall_group.command("train")
@click.option("--model", "model_path", type=str, required=False, default=None,
              help="Path to AgentClassifier script (e.g. detectors/one_class_svm.py)")
@click.option("--last", "last_n", type=int, default=10,
              help="Last N finished experiments (default: 10)")
@click.option("--from", "from_date", type=str, default=None)
@click.option("--until", "until_date", type=str, default=None)
@click.option("--min-samples", type=int, default=30)
@click.option("--output", "-o", type=click.Path(), default=None)
@click.option("--import", "import_files", type=str, multiple=True,
              help="Import external logs (e.g. results.json or results.json:promptfoo)")
def train_command(model_path, last_n, from_date, until_date, min_samples,
                  output, import_files):
    """Train Tier 2 classifiers from adversarial + QA test logs."""
    if not model_path:
        # Default to SetFit classifier shipped with hb-firewall
        import importlib.resources
        try:
            # Try to find setfit_classifier.py relative to hb_firewall package
            import hb_firewall
            pkg_dir = Path(hb_firewall.__file__).parent.parent.parent
            default = pkg_dir / "detectors" / "setfit_classifier.py"
            if default.exists():
                model_path = str(default)
            else:
                console.print("[red]Default SetFit classifier not found.[/red]")
                console.print("  Provide a path to an AgentClassifier script:")
                console.print("  hb firewall train --model detectors/setfit_classifier.py")
                sys.exit(1)
        except Exception:
            console.print("[red]Provide --model flag.[/red]")
            console.print("  hb firewall train --model detectors/setfit_classifier.py")
            sys.exit(1)

    try:
        client = HumanboundClient()
        project_id = client.project_id
        if not project_id:
            console.print("[red]No active project.[/red] Run: hb projects use <id>")
            sys.exit(1)

        # Load detector
        try:
            from hb_firewall.hbfw import HBFW, load_model_class, save_hbfw
        except ImportError:
            console.print("[red]Install: pip install hb-firewall[/red]")
            sys.exit(1)

        try:
            detector_cls = load_model_class(model_path)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

        console.print(f"\n[bold]Training firewall classifiers[/bold]")
        console.print(f"  Project: {project_id[:8]}...")
        console.print(f"  Model: {model_path}")

        # Step 1: Fetch experiments
        console.print(f"\n[bold]Step 1:[/bold] Fetching experiments...")
        adv_exps = _fetch_experiments(client, "adversarial", last_n=last_n,
                                       from_date=from_date, until_date=until_date)
        qa_exps = _fetch_experiments(client, "adversarial", exclude=True,
                                      last_n=last_n, from_date=from_date, until_date=until_date)
        if not adv_exps:
            console.print("[red]No finished adversarial experiments.[/red] Run: hb test")
            sys.exit(1)
        console.print(f"  Found {len(adv_exps)} adversarial + {len(qa_exps)} QA experiments")

        # Step 2: Fetch logs
        console.print(f"\n[bold]Step 2:[/bold] Pulling conversation logs...")
        logs = _fetch_logs(client, adv_exps + qa_exps)

        # Import external logs if provided
        if import_files:
            from hb_firewall.adapters import convert_file
            for import_arg in import_files:
                # Parse file:format syntax
                if ":" in import_arg and not import_arg.startswith("/"):
                    file_path, fmt = import_arg.rsplit(":", 1)
                else:
                    file_path, fmt = import_arg, ""
                try:
                    imported = convert_file(file_path, fmt)
                    logs.extend(imported)
                    console.print(f"  Imported {len(imported)} logs from {file_path}")
                except (ValueError, FileNotFoundError) as e:
                    console.print(f"  [red]Import failed: {e}[/red]")

        if len(logs) < min_samples:
            console.print(f"[red]Only {len(logs)} conversations (min: {min_samples}).[/red]")
            sys.exit(1)

        n_pass = sum(1 for l in logs if l.get("result") == "pass")
        n_fail = len(logs) - n_pass
        adv_fail = sum(1 for l in logs
                       if "adversarial" in (l.get("test_category") or "")
                       and l.get("result") == "fail")
        console.print(f"  Collected {len(logs)} conversations ({n_pass} pass, {n_fail} fail)")
        console.print(f"  Training on {adv_fail} failed adversarial conversations")

        permitted, restricted = _fetch_intents(client, project_id)
        if permitted or restricted:
            console.print(f"  Intents: {len(permitted or [])} permitted, {len(restricted or [])} restricted")

        # Step 3: Prepare
        console.print(f"\n[bold]Step 3:[/bold] Preparing training data...")
        hbfw = HBFW(attack_detector=detector_cls("attack"),
                     benign_detector=detector_cls("benign"))
        data = hbfw.prepare(logs, restricted_intents=restricted, permitted_intents=permitted)

        stats = data.get("stats", {})
        console.print(f"  Attack samples: {stats.get('attack_samples', 0)} (curated: {stats.get('curated_attack', 0)})")
        console.print(f"  Benign samples: {stats.get('benign_samples', 0)} (curated: {stats.get('curated_benign', 0)})")
        if not data.get("has_qa"):
            console.print(f"  [yellow]No QA tests. Using permitted intents as benign data.[/yellow]")

        # Step 4: Train
        console.print(f"\n[bold]Step 4:[/bold] Training...")
        performance = hbfw.train(data, permitted_intents=permitted,
                                  restricted_intents=restricted)

        val = performance.get("validation")
        if val:
            af = val.get("adversarial_fail", {})
            ap = val.get("adversarial_pass", {})
            bn = val.get("benign", {})
            console.print(f"\n  [bold]Validation (conversation replay)[/bold]")
            if af.get("total"):
                r = af.get("rate", 0)
                s = "green" if r >= 0.8 else "yellow" if r >= 0.5 else "red"
                console.print(f"    Failed adversarial caught: [{s}]{af['caught']}/{af['total']} ({r:.1%})[/{s}]")
            if ap.get("total"):
                r = ap.get("rate", 0)
                s = "green" if r >= 0.5 else "dim"
                console.print(f"    Passed adversarial caught: [{s}]{ap['caught']}/{ap['total']} ({r:.1%})[/{s}]")
            if bn.get("total"):
                r = bn.get("rate", 0)
                s = "green" if r >= 0.8 else "yellow" if r >= 0.5 else "red"
                console.print(f"    Benign allowed: [{s}]{bn['correct']}/{bn['total']} ({r:.1%})[/{s}]")
                if bn.get("blocked"):
                    console.print(f"    [red]Benign blocked: {bn['blocked']}[/red]")

        console.print(f"  Training complete.")

        # Save
        if output is None:
            output = f"firewall_{project_id[:8]}.hbfw"
        model_data = hbfw.export()
        model_data["config"]["project_id"] = project_id
        model_data["config"]["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        model_data["config"]["n_conversations"] = len(logs)
        model_data["config"]["detector"] = Path(model_path).stem
        save_hbfw(model_data, output)

        file_size = Path(output).stat().st_size / 1024
        console.print(f"\n[green]Model saved:[/green] {output} ({file_size:.0f} KB)")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run: hb login")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@firewall_group.command("show")
@click.argument("model_path", type=click.Path(exists=True))
def show_command(model_path):
    """Show model info from a trained .hbfw file."""
    try:
        from hb_firewall.hbfw import load_hbfw
    except ImportError:
        console.print("[red]hb-firewall not installed.[/red]")
        sys.exit(1)

    config, _ = load_hbfw(model_path)
    console.print(f"\n[bold]Firewall Model: {model_path}[/bold]")
    console.print(f"  Created: {config.get('created_at', '?')}")
    console.print(f"  Project: {config.get('project_id', '?')}")
    console.print(f"  Detector: {config.get('detector', '?')}")
    perf = config.get("performance", {})
    stats = perf.get("stats", {})
    if stats:
        console.print(f"  Attack samples: {stats.get('attack_samples', '?')}")
        console.print(f"  Benign samples: {stats.get('benign_samples', '?')}")
    val = perf.get("validation")
    if val:
        af = val.get("adversarial_fail", {})
        ap = val.get("adversarial_pass", {})
        bn = val.get("benign", {})
        console.print(f"  Validation:")
        if af.get("total"):
            console.print(f"    Failed adversarial caught: {af['caught']}/{af['total']} ({af.get('rate',0):.1%})")
        if ap.get("total"):
            console.print(f"    Passed adversarial caught: {ap['caught']}/{ap['total']} ({ap.get('rate',0):.1%})")
        if bn.get("total"):
            console.print(f"    Benign allowed: {bn['correct']}/{bn['total']} ({bn.get('rate',0):.1%})")




# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_experiments(client, category, exclude=False, last_n=10,
                       from_date=None, until_date=None):
    experiments = []
    page = 1
    while True:
        result = client.list_experiments(page=page, size=50)
        for exp in result.get("data", []):
            if exp.get("status") != "Finished":
                continue
            has = category in exp.get("test_category", "")
            if exclude and has:
                continue
            if not exclude and not has:
                continue
            created = exp.get("created_at", "")
            if from_date and created < from_date:
                continue
            if until_date and created > until_date:
                continue
            experiments.append(exp)
        if not result.get("has_next_page"):
            break
        page += 1
    experiments.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return experiments[:last_n]


def _fetch_logs(client, experiments):
    all_logs = []
    with Progress(console=console) as progress:
        task = progress.add_task("  Fetching...", total=len(experiments))
        for exp in experiments:
            cat = exp.get("test_category", "")
            page = 1
            while True:
                result = client.get_experiment_logs(exp["id"], page=page, size=100)
                for log in result.get("data", []):
                    log["test_category"] = cat
                all_logs.extend(result.get("data", []))
                if not result.get("has_next_page"):
                    break
                page += 1
            progress.advance(task)
    return all_logs


def _fetch_intents(client, project_id):
    try:
        data = client.get(f"projects/{project_id}")
        intents = data.get("scope", {}).get("intents", {})
        return intents.get("permitted", []), intents.get("restricted", [])
    except Exception:
        return None, None


