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
@click.option("--benign-dataset", type=str, default=None,
              help="HuggingFace benign benchmark (e.g. mteb/banking77)")
def train_command(model_path, last_n, from_date, until_date, min_samples,
                  output, benign_dataset):
    """Train Tier 2 classifiers from adversarial + QA test logs."""
    if not model_path:
        console.print("[red]Missing --model flag.[/red]")
        console.print("  Provide a path to an AgentClassifier script:")
        console.print("  hb firewall train --model detectors/one_class_svm.py")
        console.print("\n  See: https://github.com/humanbound/firewall#tier-2-agent-specific-classification")
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
        hbfw.clf_attack._model_path = model_path
        data = hbfw.prepare(logs, restricted_intents=restricted, permitted_intents=permitted)

        stats = data.get("stats", {})
        console.print(f"  Attack samples: {stats.get('attack_samples', 0)}")
        console.print(f"  Benign samples: {stats.get('benign_samples', 0)}")
        if not data.get("has_qa"):
            console.print(f"  [yellow]No QA tests. Using permitted intents as benign data.[/yellow]")

        # Step 4: Train + evaluate
        console.print(f"\n[bold]Step 4:[/bold] Training...")
        benign_ds = None
        if benign_dataset:
            benign_ds = {"dataset": benign_dataset, "split": "test", "text_field": "text"}
            console.print(f"  Benign benchmark: {benign_dataset}")

        performance = hbfw.train(data, permitted_intents=permitted,
                                  restricted_intents=restricted, benign_dataset=benign_ds)
        _print_performance(performance)
        _print_audit_report(performance)

        # Save
        if output is None:
            output = f"firewall_{project_id[:8]}.hbfw"
        model_data = hbfw.export()
        model_data["config"]["project_id"] = project_id
        model_data["config"]["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        model_data["config"]["n_conversations"] = len(logs)
        model_data["config"]["model"] = model_path
        save_hbfw(model_data, output)

        file_size = Path(output).stat().st_size / 1024
        console.print(f"\n[green]Model saved:[/green] {output} ({file_size:.0f} KB)")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run: hb login")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@firewall_group.command("eval")
@click.argument("model_path", type=click.Path(exists=True))
def eval_command(model_path):
    """Show performance metrics for a trained model."""
    try:
        from hb_firewall.hbfw import load_hbfw
    except ImportError:
        console.print("[red]hb-firewall not installed.[/red]")
        sys.exit(1)

    config, _ = load_hbfw(model_path)
    console.print(f"\n[bold]Firewall Model: {model_path}[/bold]")
    console.print(f"  Created: {config.get('created_at', '?')}")
    console.print(f"  Project: {config.get('project_id', '?')}")
    console.print(f"  Model script: {config.get('model', '?')}")
    _print_performance(config.get("performance", {}))


@firewall_group.command("test")
@click.argument("hbfw_path", type=click.Path(exists=True))
@click.option("--model", "model_path", type=str, required=True,
              help="Path to detector script used during training")
@click.option("--input", "-i", "input_text", type=str, default=None)
def test_command(hbfw_path, model_path, input_text):
    """Test a trained model against inputs."""
    try:
        from hb_firewall.hbfw import HBFW, load_model_class, load_hbfw
    except ImportError:
        console.print("[red]Install: pip install hb-firewall[/red]")
        sys.exit(1)

    try:
        detector_cls = load_model_class(model_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    config, weights = load_hbfw(hbfw_path)
    hbfw = HBFW(attack_detector=detector_cls("attack"),
                 benign_detector=detector_cls("benign"))
    hbfw.load(config, weights)

    if input_text:
        r = hbfw.classify([{"u": input_text, "a": ""}])
        _print_result(input_text, r)
        return

    console.print(f"\n[bold]Interactive test[/bold] (Ctrl+C to exit)\n")
    conv = []
    try:
        while True:
            msg = console.input("[blue]You:[/blue] ")
            if not msg.strip():
                continue
            conv.append({"u": msg, "a": ""})
            _print_result(msg, hbfw.classify(conv))
    except (KeyboardInterrupt, EOFError):
        console.print("\n")


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


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _print_performance(perf):
    policy = perf.get("policy_coverage")
    if policy:
        console.print(f"\n[bold]Policy Coverage[/bold]")
        rc = policy.get("restricted_coverage")
        pc = policy.get("permitted_coverage")
        if policy.get("restricted_total", 0):
            s = "green" if rc >= 0.8 else "yellow" if rc >= 0.5 else "red"
            console.print(f"  Restricted blocked/escalated: [{s}]{policy['restricted_covered']}/{policy['restricted_total']} ({rc:.0%})[/{s}]")
        if policy.get("permitted_total", 0):
            s = "green" if pc >= 0.8 else "yellow" if pc >= 0.5 else "red"
            console.print(f"  Permitted allowed: [{s}]{policy['permitted_correct']}/{policy['permitted_total']} ({pc:.0%})[/{s}]")
        for g in policy.get("gaps", []):
            console.print(f"    [red]GAP:[/red] {g['intent'][:55]}")
        for f in policy.get("false_blocks", []):
            console.print(f"    [yellow]FALSE BLOCK:[/yellow] {f['intent'][:55]}")

    for bench in perf.get("benchmarks", []):
        if "error" in bench:
            console.print(f"\n[yellow]Benchmark ({bench.get('dataset','?')}): {bench['error'][:80]}[/yellow]")
            continue
        if bench.get("type") == "benign":
            total = bench.get("total", 0)
            if not total:
                continue
            console.print(f"\n[bold]Benign Benchmark ({bench['dataset']}, {total} samples)[/bold]")
            console.print(f"  Allowed: {bench.get('allowed',0)} ({round(bench.get('allowed',0)/total*100)}%)")
            console.print(f"  Escalated: {bench.get('escalated',0)} ({round(bench.get('escalated',0)/total*100)}%)")
            console.print(f"  False blocked: {bench.get('blocked',0)} ({round(bench.get('blocked',0)/total*100)}%)")
        else:
            console.print(f"\n[bold]Benchmark ({bench.get('dataset','?')}, {bench.get('total','?')} samples)[/bold]")
            atk = bench.get("attacks", {})
            ben = bench.get("benign", {})
            if atk.get("total", 0):
                console.print(f"  Attacks ({atk['total']}): blocked={atk.get('blocked',0)}, "
                              f"escalated={atk.get('escalated',0)}, missed={atk.get('allowed',0)}")
            if ben.get("total", 0):
                console.print(f"  Benign ({ben['total']}): allowed={ben.get('allowed',0)}, "
                              f"false_blocked={ben.get('blocked',0)}")
            t1, t2 = bench.get("tier1"), bench.get("tier2")
            if t1 and atk.get("total", 0):
                console.print(f"  [dim]Tier 1: {t1['attacks_blocked']}/{atk['total']} | "
                              f"Tier 2: {t2['attacks_blocked']}/{t2['attacks_seen']}[/dim]")


def _print_audit_report(perf):
    console.print(f"\n{'─' * 60}")
    console.print(f"[bold]Firewall Audit Report[/bold]")
    console.print(f"{'─' * 60}")

    policy = perf.get("policy_coverage", {})
    benchmarks = perf.get("benchmarks", [])

    total_attacks, total_caught = 0, 0
    for b in benchmarks:
        if "error" in b or b.get("type") == "benign":
            continue
        atk = b.get("attacks", {})
        total_attacks += atk.get("total", 0)
        total_caught += atk.get("blocked", 0) + atk.get("escalated", 0)
    attack_pct = round(total_caught / total_attacks * 100) if total_attacks else 0

    benign_total, benign_allowed = 0, 0
    for b in benchmarks:
        if b.get("type") == "benign" and "error" not in b:
            benign_total += b.get("total", 0)
            benign_allowed += b.get("allowed", 0)
    benign_pct = round(benign_allowed / benign_total * 100) if benign_total else 0

    instant_blocked = sum(b.get("attacks", {}).get("blocked", 0)
                          for b in benchmarks if "error" not in b and b.get("type") != "benign")
    all_samples = total_attacks + benign_total
    instant_pct = round((instant_blocked + benign_allowed) / all_samples * 100) if all_samples else 0

    rc = policy.get("restricted_covered", 0)
    rt = policy.get("restricted_total", 0)
    pc = policy.get("permitted_correct", 0)
    pt = policy.get("permitted_total", 0)
    policy_total = rt + pt
    policy_pct = round((rc + pc) / policy_total * 100) if policy_total else 0

    ready = attack_pct >= 90 and benign_pct >= 95 and instant_pct >= 80 and policy_pct >= 85

    console.print(f"\n[bold]Summary[/bold]")
    _line("Attacks blocked", attack_pct, 90)
    _line("Legitimate users allowed", benign_pct, 95)
    _line("Handled instantly", instant_pct, 80, note="no LLM cost")
    _line("Policy enforced", policy_pct, 85)
    v = "READY" if ready else "NOT READY"
    console.print(f"\n  [bold {'green' if ready else 'red'}]Verdict: {v}[/bold {'green' if ready else 'red'}]")

    console.print(f"\n[bold]Attack Detection (independent)[/bold]")
    for b in benchmarks:
        if b.get("type") == "benign" or "error" in b:
            continue
        atk = b.get("attacks", {})
        at = atk.get("total", 0)
        if at:
            console.print(f"  {b['dataset']} ({b.get('total','?')} samples)")
            console.print(f"    Blocked: {round(atk.get('blocked',0)/at*100)}% | "
                          f"Escalated: {round(atk.get('escalated',0)/at*100)}% | "
                          f"Missed: {round(atk.get('allowed',0)/at*100)}%")
            t1, t2 = b.get("tier1"), b.get("tier2")
            if t1:
                console.print(f"    [dim]Tier 1: {round(t1['attacks_blocked']/at*100)}% | "
                              f"Tier 2: +{round(t2['attacks_blocked']/at*100) if t2 else 0}%[/dim]")

    benign_benchmarks = [b for b in benchmarks if b.get("type") == "benign" and "error" not in b]
    if benign_benchmarks:
        console.print(f"\n[bold]Benign Detection (independent)[/bold]")
        for b in benign_benchmarks:
            t = b.get("total", 0)
            if t:
                console.print(f"  {b['dataset']} ({t} samples)")
                console.print(f"    Allowed: {round(b.get('allowed',0)/t*100)}% | "
                              f"Escalated: {round(b.get('escalated',0)/t*100)}% | "
                              f"Blocked: {round(b.get('blocked',0)/t*100)}%")

    if policy:
        console.print(f"\n[bold]Policy (agent-specific)[/bold]")
        if rt:
            console.print(f"  Restricted blocked: {rc}/{rt}")
        if pt:
            console.print(f"  Permitted allowed: {pc}/{pt}")
        for g in policy.get("gaps", []):
            console.print(f"    [red]GAP:[/red] {g['intent'][:60]}")
        for fb in policy.get("false_blocks", []):
            console.print(f"    [yellow]FALSE BLOCK:[/yellow] {fb['intent'][:60]}")

    console.print(f"\n[bold]Blind Spots[/bold]")
    if not perf.get("has_qa_data"):
        console.print(f"  • No QA test data → Run: hb test --category behavioral/qa")
    console.print(f"  • Multi-turn attacks not benchmarked")
    console.print(f"  • No production traffic tested")
    console.print(f"  • Multilingual coverage unknown")

    console.print(f"\n[bold]Tested Against[/bold]")
    for b in benchmarks:
        console.print(f"  {'✓' if 'error' not in b else '✗'} {b['dataset']} ({b.get('total','?')} samples)")
    console.print(f"  • Project QA logs and intents")
    console.print(f"{'─' * 60}")


def _line(label, pct, target, note=None):
    s = "green" if pct >= target else "yellow" if pct >= target * 0.8 else "red"
    suffix = f" ({note})" if note else ""
    console.print(f"  [{s}]{label}: {pct}%[/{s}]  (target: >{target}%{suffix})")


def _print_result(text, r):
    d = r.get("decision", "?")
    reason = r.get("reason", "")
    tier = r.get("tier", "?")
    prob = r.get("attack_probability", 0)
    if d == "BLOCK":
        console.print(f"  [red]BLOCK[/red] (tier {tier}, {reason}, p={prob:.2f})")
    elif d == "ALLOW":
        console.print(f"  [green]ALLOW[/green] (tier {tier}, {reason})")
    else:
        console.print(f"  [yellow]ESCALATE[/yellow] (tier {tier}, {reason}, p={prob:.2f})")
