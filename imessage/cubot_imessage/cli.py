"""Command line for the bridge.

    cubot-imessage doctor                       check the wiring before the demo
    cubot-imessage vocab                        what the robot can fold, and where every label routes
    cubot-imessage classify "show htn love"     the language path only, with scores
    cubot-imessage simulate "make a heart"      the whole handler, no HTTP and no Linq
    cubot-imessage plan heart                   the fold path a shape resolves to
    cubot-imessage serve                        run the webhook server
    cubot-imessage send --to +1555... "hi"      outbound iMessage (prints unless --send is passed)
    cubot-imessage subscribe --url https://...  register the webhook (prints unless --send is passed)

`send` and `subscribe` are dry-run by default: they print the exact request and send nothing until you
add `--send`. Everything else is local and touches no network.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .bridge import Bridge
from .config import Settings
from .intent import Classifier, IntentUnavailable
from .linq import InboundMessage, LinqClient
from .robot import ShapeLibrary, build_executor, states_match_goal
from .vocab import (CUBOT_PLANNABLE, CUBOT_REJECTED, STATUS_PLAYABLE, Vocabulary, label_to_icon)

PROG = "cubot-imessage"


def _bridge(settings: Settings, execute: bool = True, log=print) -> Bridge:
    client = None
    if settings.api_key and (settings.auto_reply or settings.react_on_receive):
        client = LinqClient(settings.api_key, settings.base_url, settings.timeout_s,
                            settings.from_number)
    viewer_base = settings.viewer_base or f"http://127.0.0.1:{settings.port}/sim"
    executor = build_executor(settings.executor, viewer_base=viewer_base, log=log)
    return Bridge(settings, executor=executor, client=client, log=log)


# ------------------------------------------------------------------------------------ commands

def cmd_doctor(args, settings: Settings) -> int:
    print("configuration")
    for label, value in settings.describe():
        print(f"  {label:16} {value}")

    print("\nhandoff")
    try:
        vocab = Vocabulary(settings.handoff_dir)
        library = ShapeLibrary(settings.handoff_dir)
        print(f"  roll word        {vocab.roll}")
        print(f"  playable         {len(vocab.playable)}: {', '.join(vocab.playable)}")
        bad = []
        for name in library.names:
            plan = library.plan(name)
            consistent = states_match_goal(plan)
            flag = "" if consistent else "  <-- deltas do not reach the recorded goal"
            if not consistent:
                bad.append(name)
            warn = ("  ! " + "; ".join(plan.warnings)) if plan.warnings else ""
            print(f"    {plan.number}. {plan.shape:10} {len(plan.moves):2d} moves "
                  f"{plan.total_time_s:5.1f}s{warn}{flag}")
        print(f"  consistency      {'OK' if not bad else 'FAILED for ' + ', '.join(bad)}")
    except (OSError, ValueError, KeyError) as e:
        print(f"  ERROR: {e}")
        return 1

    print("\nintent model")
    try:
        clf = Classifier.from_settings(settings)
        clf.warmup()
        margin, conf = clf.thresholds
        print(f"  head             {clf.head_path}")
        print(f"  encoder          {clf.encoder_name}")
        print(f"  stale            {'YES — retrain' if clf.is_stale() else 'no'}")
        print(f"  labels           {len(clf.labels)}")
        print(f"  thresholds       margin >= {margin}, confidence >= {conf}")
        print(f"  load time        {clf.load_seconds:.2f}s")
        probe = "show hack the north some love"
        res = clf.classify(probe)
        print(f"  probe            {probe!r} -> {res.label} "
              f"(conf {res.confidence:.2f}, margin {res.margin:.2f}, {res.latency_ms:.0f}ms)")
        routed = sorted(set(vocab.playable_labels().values()))
        print(f"  labels routing to a playable shape: {len(vocab.playable_labels())} "
              f"-> {', '.join(routed)}")
    except IntentUnavailable as e:
        print(f"  ERROR: {e}")
        return 1
    print("\nready" if settings.api_key else "\nready (local only — LINQ_API_KEY unset, cannot reply)")
    return 0


def cmd_vocab(args, settings: Settings) -> int:
    vocab = Vocabulary(settings.handoff_dir)
    playable = set(vocab.playable)
    print(f"playable now ({len(playable)}) — a finalized fold path exists in handoff/shapes/")
    for name in vocab.playable:
        flagged, why = vocab.is_flagged(name)
        print(f"  {name:12}{'  ! ' + why if flagged else ''}")
    pending = [n for n in CUBOT_PLANNABLE if n not in playable]
    print(f"\nplannable ({len(pending)}) — verified in cubot-v2, not exported to handoff/ yet")
    print("  " + ", ".join(pending))
    print(f"  -> make these playable with:  cd cubot-v2 && uv run python tools/export_handoff.py "
          f"--manifest out/<run>/handoff-manifest.json")
    print(f"\nrejected ({len(CUBOT_REJECTED)}) — dropped in review for recognizability")
    print("  " + ", ".join(CUBOT_REJECTED))

    if args.labels:
        try:
            clf = Classifier.from_settings(settings)
            labels = clf.labels
        except IntentUnavailable as e:
            print(f"\n(cannot list label routing: {e})")
            return 0
        print(f"\nlabel routing ({len(labels)} classifier labels)")
        rows = []
        for label in labels:
            icon = label_to_icon(label)
            shape = vocab.shape_for_icon(icon)
            where = shape if shape else ("plannable" if icon in CUBOT_PLANNABLE else
                                         "rejected" if icon in CUBOT_REJECTED else "-")
            rows.append((label, icon, where))
        for label, icon, where in sorted(rows, key=lambda r: (r[2] == "-", r[2], r[0])):
            print(f"  {label:14} -> {icon:14} {where}")
    return 0


def cmd_classify(args, settings: Settings) -> int:
    clf = Classifier.from_settings(settings)
    vocab = Vocabulary(settings.handoff_dir)
    try:
        clf.warmup()
    except IntentUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    playable_labels = vocab.playable_labels()
    for text in args.text:
        res = clf.classify(text, top_k=args.top)
        nearest = clf.restricted_best(text, list(playable_labels))
        resolution = vocab.resolve(res.label, res.accepted, nearest, playable_labels)
        print(f"{text!r}")
        print(f"  label      {res.label}  (confidence {res.confidence:.3f}, margin {res.margin:.3f}, "
              f"{'accepted' if res.accepted else 'BELOW THRESHOLD'})")
        print(f"  caption    {res.caption!r}" + (f"   who={res.who!r}" if res.who else ""))
        print(f"  resolution {resolution.status}"
              + (f" -> {resolution.shape}" if resolution.shape else "")
              + (f"   ({resolution.detail})" if resolution.detail else ""))
        if resolution.status != STATUS_PLAYABLE and resolution.nearest_playable:
            print(f"  nearest    {resolution.nearest_playable} (score {resolution.nearest_score:.3f})")
        if args.top > 1:
            print("  top        " + ", ".join(f"{l}={s:.3f}" for l, s in res.ranked))
        print(f"  latency    {res.latency_ms:.1f}ms")
    return 0


def cmd_simulate(args, settings: Settings) -> int:
    """The whole handler on a fabricated inbound message — no HTTP, no Linq, nothing sent."""
    settings.auto_reply = False
    bridge = _bridge(settings)
    try:
        bridge.warmup()
    except IntentUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for i, text in enumerate(args.text):
        inbound = InboundMessage(event_id=f"sim-{i}", message_id=f"sim-{i}",
                                 chat_id="sim-chat", sender=args.sender, text=text)
        print(f"\n--- {text!r}")
        out = bridge.handle(inbound, execute=not args.no_execute)
        print(f"status  {out.status}")
        if out.intent:
            print(f"label   {out.intent.label} (conf {out.intent.confidence:.3f}, "
                  f"margin {out.intent.margin:.3f})")
        if out.plan:
            print(f"plan    {out.plan.summary_line()}")
        if out.error:
            print(f"error   {out.error}")
        print(f"reply   {out.reply}")
    return 0


def cmd_plan(args, settings: Settings) -> int:
    vocab = Vocabulary(settings.handoff_dir)
    library = ShapeLibrary(settings.handoff_dir)
    shape = vocab.shape_for_icon(args.shape) or args.shape
    try:
        plan = library.plan(shape)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
        return 0
    print(plan.summary_line())
    for w in plan.warnings:
        print(f"  ! {w}")
    print(f"  path.json  {plan.path_json}")
    print(f"  start base {plan.start_base}  ->  final base {plan.final_base}")
    print(f"  deltas reach the recorded goal: {states_match_goal(plan)}")
    if plan.goal_silhouette:
        print("  goal:")
        for row in plan.goal_silhouette:
            print(f"    {row}")
    print(f"  {len(plan.moves)} moves (step joint delta side):")
    for m in plan.moves:
        print(f"    {m.step:3d}  j{m.joint:<3d} {m.delta:+d}  {m.side:3}  "
              f"{m.duration_s:.1f}s  peak {m.peak_demand_nm:5.2f} N·m"
              f"{'' if m.hard_ok else '   HARD CHECK FAILED'}")
    return 0


def cmd_serve(args, settings: Settings) -> int:
    from .server import serve                    # noqa: PLC0415 — keeps `--help` from importing http
    if args.port:
        settings.port = args.port
    if args.host:
        settings.host = args.host
    if args.executor:
        settings.executor = args.executor
    if args.no_reply:
        settings.auto_reply = False
    if settings.auto_reply and not settings.api_key:
        print("note: LINQ_API_KEY is unset, so replies are disabled; running read-only",
              file=sys.stderr)
        settings.auto_reply = False
    bridge = _bridge(settings)
    if args.spool:
        settings.executor = "spool"
        bridge.executor = build_executor("spool", args.spool)
    serve(settings, bridge)
    return 0


def cmd_send(args, settings: Settings) -> int:
    client = LinqClient(settings.api_key, settings.base_url, settings.timeout_s,
                        settings.from_number, dry_run=not args.send)
    result = client.send_to(args.to, args.text)
    if not args.send:
        print("DRY RUN — nothing sent. Re-run with --send to transmit.")
    print(json.dumps(result, indent=2))
    return 0


def cmd_subscribe(args, settings: Settings) -> int:
    url = args.url
    if settings.webhook_token and "token=" not in url:
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}token={settings.webhook_token}"
    client = LinqClient(settings.api_key, settings.base_url, settings.timeout_s,
                        dry_run=not args.send)
    result = client.create_subscription(url, tuple(args.events))
    if not args.send:
        print("DRY RUN — nothing registered. Re-run with --send to create the subscription.")
    print(json.dumps(result, indent=2))

    # Linq returns the signing secret once and never again; missing it means deleting the
    # subscription and making a new one. Do not let it scroll past in a blob of JSON.
    secret = result.get("signing_secret") if isinstance(result, dict) else None
    if secret:
        print("\n" + "=" * 78)
        print("SAVE THIS NOW — Linq shows the signing secret only once:")
        print(f"\n    LINQ_WEBHOOK_SECRET={secret}\n")
        print("Put it in imessage/.env. Without it the bridge cannot verify signatures and falls")
        print("back to the URL token. To get a new one you must delete and recreate this")
        print("subscription.")
        print("=" * 78)
    elif args.send:
        print("\n[warn] no signing_secret in the response — signature verification will be "
              "unavailable; the bridge will authenticate on the URL token alone.")
    return 0


# ------------------------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description="iMessage (Linq) -> MiniLM -> CuBot V2 fold paths.")
    p.add_argument("--handoff", help="override CUBOT_HANDOFF_DIR")
    p.add_argument("--head", help="override the trained head path")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check config, handoff paths and the intent model").set_defaults(
        func=cmd_doctor)

    v = sub.add_parser("vocab", help="playable / plannable / rejected shapes")
    v.add_argument("--labels", action="store_true", help="also print where every classifier label routes")
    v.set_defaults(func=cmd_vocab)

    c = sub.add_parser("classify", help="classify utterances (language path only)")
    c.add_argument("text", nargs="+")
    c.add_argument("--top", type=int, default=5, help="how many ranked labels to show (default 5)")
    c.set_defaults(func=cmd_classify)

    s = sub.add_parser("simulate", help="run the full handler on fabricated inbound messages")
    s.add_argument("text", nargs="+")
    s.add_argument("--sender", default="+15555550123")
    s.add_argument("--no-execute", action="store_true", help="classify and reply but skip the executor")
    s.set_defaults(func=cmd_simulate)

    pl = sub.add_parser("plan", help="print a shape's fold path")
    pl.add_argument("shape")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_plan)

    sv = sub.add_parser("serve", help="run the webhook server")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)
    sv.add_argument("--executor", choices=("dryrun", "spool", "viewer", "mujoco", "none"))
    sv.add_argument("--spool", help="JSONL queue file (implies --executor spool)")
    sv.add_argument("--no-reply", action="store_true", help="never send an iMessage back")
    sv.set_defaults(func=cmd_serve)

    sd = sub.add_parser("send", help="send an outbound iMessage (dry run unless --send)")
    sd.add_argument("text")
    sd.add_argument("--to", action="append", required=True, help="E.164 recipient; repeatable")
    sd.add_argument("--send", action="store_true", help="actually transmit")
    sd.set_defaults(func=cmd_send)

    su = sub.add_parser("subscribe", help="register the webhook with Linq (dry run unless --send)")
    su.add_argument("--url", required=True, help="public HTTPS URL of this server's webhook path")
    su.add_argument("--events", nargs="+", default=["message.received"])
    su.add_argument("--send", action="store_true", help="actually create the subscription")
    su.set_defaults(func=cmd_subscribe)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load()
    if args.handoff:
        settings.handoff_dir = args.handoff
    if getattr(args, "head", None):
        settings.head_path = args.head
    try:
        return int(args.func(args, settings) or 0)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
