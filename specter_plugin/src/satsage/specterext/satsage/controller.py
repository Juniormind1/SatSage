"""Flask-Blueprint für die SatSage Specter-Extension."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import current_app as app
from flask import redirect, render_template, request, url_for
from flask_login import login_required

from .bridge import (
    build_context,
    find_wallet_by_alias,
    wallet_to_info,
    wallet_transactions,
    wallet_utxos,
)
from .service import SatsageService

logger = logging.getLogger(__name__)

satsage_endpoint = SatsageService.blueprint

_PLUGIN_DIR = Path(__file__).resolve().parents[4]
_SATSAGE_ROOT = _PLUGIN_DIR.parent


def _session(force: bool = False):
    from .specter_session import get_session

    return get_session(app.specter, force_reload=force)


@satsage_endpoint.route("/gui")
@login_required
def gui():
    """
    Volle Web-GUI (server.py + web/) per iframe.

    Startet den lokalen GUI-Server bei Bedarf und speist Specter-Wallets ein.
    Fallback-Link öffnet dieselbe URL in einem neuen Tab (falls CSP das
    iframe blockiert).
    """
    gui_info = None
    error = None
    try:
        from .gui_server import ensure_gui_server

        gui_info = ensure_gui_server(app.specter)
    except Exception as exc:
        logger.exception("GUI-Server")
        error = str(exc)

    return render_template(
        "satsage/gui.jinja",
        service=SatsageService,
        gui=gui_info,
        gui_url=(gui_info or {}).get("url") or "",
        error=error,
        active_tab="gui",
    )


@satsage_endpoint.route("/")
@login_required
def index():
    ctx = build_context(app.specter)
    preview_limit = int(app.config.get("SATSAGE_PREVIEW_LIMIT", 25))
    show_sensitive = bool(app.config.get("SATSAGE_SHOW_SENSITIVE", False))
    session_info = None
    session_error = None
    try:
        sess = _session()
        session_info = {
            "source": sess.source,
            "address_count": len(sess.own_addresses),
            "utxo_count": len(sess.specter_utxos),
            "privacy": None,
        }
        from .specter_session import ensure_satsage_on_path

        ensure_satsage_on_path()
        import main as xq_main

        session_info["privacy"] = xq_main.privacy_notice_for_source(
            sess.source, fulcrum=sess.fetchers.get("fulcrum")
        )
    except Exception as exc:
        logger.exception("Session-Init")
        session_error = str(exc)

    return render_template(
        "satsage/index.jinja",
        service=SatsageService,
        ctx=ctx.to_dict(include_secrets=show_sensitive),
        wallet_count=len(ctx.wallets),
        xpub_count=len(ctx.all_xpubs()),
        node=ctx.node,
        satsage_root=str(_SATSAGE_ROOT),
        preview_limit=preview_limit,
        session_info=session_info,
        session_error=session_error,
        active_tab="index",
    )


@satsage_endpoint.route("/wallets")
@login_required
def wallets():
    ctx = build_context(app.specter)
    show_sensitive = bool(app.config.get("SATSAGE_SHOW_SENSITIVE", False))
    return render_template(
        "satsage/wallets.jinja",
        service=SatsageService,
        wallets=ctx.wallets,
        ctx=ctx.to_dict(include_secrets=show_sensitive),
        show_sensitive=show_sensitive,
        active_tab="wallets",
    )


@satsage_endpoint.route("/wallet/<wallet_alias>")
@login_required
def wallet_detail(wallet_alias: str):
    limit = int(app.config.get("SATSAGE_PREVIEW_LIMIT", 25))
    wallet = find_wallet_by_alias(app.specter, wallet_alias)
    if wallet is None:
        return render_template(
            "satsage/wallet_detail.jinja",
            service=SatsageService,
            error=f"Wallet '{wallet_alias}' nicht gefunden.",
            wallet_info=None,
            utxos=[],
            txs=[],
            active_tab="wallets",
        )

    info = wallet_to_info(wallet)
    utxos = wallet_utxos(wallet, limit=limit)
    txs = wallet_transactions(wallet, limit=limit)
    return render_template(
        "satsage/wallet_detail.jinja",
        service=SatsageService,
        error=None,
        wallet_info=info,
        utxos=utxos,
        txs=txs,
        active_tab="wallets",
    )


@satsage_endpoint.route("/context.json")
@login_required
def context_json():
    from flask import jsonify

    show = request.args.get("secrets") == "1" and bool(
        app.config.get("SATSAGE_SHOW_SENSITIVE", False)
    )
    ctx = build_context(app.specter)
    return jsonify(ctx.to_dict(include_secrets=show))


@satsage_endpoint.route("/reload", methods=["POST", "GET"])
@login_required
def reload_session():
    try:
        _session(force=True)
    except Exception as exc:
        logger.exception("Session reload")
        return render_template(
            "satsage/analyze_result.jinja",
            service=SatsageService,
            title="Session neu laden",
            error=str(exc),
            output="",
            active_tab="analyze",
        )
    return redirect(url_for(f"{SatsageService.get_blueprint_name()}.index"))


@satsage_endpoint.route("/analyze", methods=["GET", "POST"])
@login_required
def analyze():
    ctx = build_context(app.specter)
    mode = (request.values.get("mode") or "form").strip()
    txid = (request.values.get("txid") or "").strip()
    utxo = (request.values.get("utxo") or "").strip()
    address = (request.values.get("address") or "").strip()
    wallet_alias = (request.values.get("wallet_alias") or "").strip() or None

    if mode in ("tx", "utxo", "rank", "trace_top"):
        try:
            sess = _session()
        except Exception as exc:
            logger.exception("Session")
            return render_template(
                "satsage/analyze_result.jinja",
                service=SatsageService,
                title="Analyse",
                error=f"Session konnte nicht gestartet werden: {exc}",
                output="",
                active_tab="analyze",
            )

        from . import specter_session as ss

        output = ""
        error = None
        title = "Analyse"

        if mode == "tx":
            title = f"Tx-Trace {txid[:16]}…" if txid else "Tx-Trace"
            output, error = ss.run_analyze_tx(sess, txid)
        elif mode == "utxo":
            title = f"UTXO-Trace {utxo}" if utxo else "UTXO-Trace"
            output, error = ss.run_analyze_utxo(sess, utxo, address=address or None)
        elif mode == "rank":
            title = "UTXO-Rangfolge"
            limit = int(app.config.get("SATSAGE_PREVIEW_LIMIT", 25))
            _ranked, output, error = ss.run_utxo_rank(
                sess, wallet_alias=wallet_alias, limit=limit
            )
        elif mode == "trace_top":
            title = "Top-UTXOs tracen"
            try:
                limit = int(request.values.get("limit") or 3)
            except ValueError:
                limit = 3
            limit = max(1, min(limit, 15))
            utxos = sess.specter_utxos
            if wallet_alias:
                name = next(
                    (w.name for w in sess.ctx.wallets if w.alias == wallet_alias),
                    None,
                )
                if name:
                    utxos = [u for u in utxos if u.get("wallet") == name]
            output, error = ss.run_trace_utxos(sess, utxos, limit=limit)

        return render_template(
            "satsage/analyze_result.jinja",
            service=SatsageService,
            title=title,
            error=error,
            output=output,
            active_tab="analyze",
        )

    session_source = None
    try:
        session_source = _session().source
    except Exception:
        pass

    return render_template(
        "satsage/analyze.jinja",
        service=SatsageService,
        wallets=ctx.wallets,
        session_source=session_source,
        active_tab="analyze",
    )
