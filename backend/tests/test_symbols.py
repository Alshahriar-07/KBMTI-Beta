from __future__ import annotations

from app.market_data.symbols import discover_btc_symbols, is_btc_like, pick_default_symbol


def symbol(name: str, description: str = "", path: str = "", trade_mode: int = 4, visible: bool = True) -> dict:
    return {
        "name": name,
        "description": description,
        "path": path,
        "trade_mode": trade_mode,
        "visible": visible,
    }


def test_btc_variants_are_discovered_and_ranked() -> None:
    candidates = discover_btc_symbols(
        [
            symbol("ETHUSD", "Ethereum vs US Dollar", "Crypto\\ETHUSD"),
            symbol("BTCUSDm", "Bitcoin vs US Dollar", "Crypto\\BTCUSDm"),
            symbol("BTCUSD.", "Bitcoin vs US Dollar", "Crypto\\BTCUSD."),
            symbol("BTCUSD", "Bitcoin / US Dollar", "Crypto\\BTCUSD"),
            symbol("XAUUSD", "Gold vs US Dollar", "Metals\\XAUUSD"),
        ]
    )
    names = [item["name"] for item in candidates]
    assert names[0] == "BTCUSD"
    assert set(names) == {"BTCUSD", "BTCUSDm", "BTCUSD."}
    assert candidates[0]["recommended"] is True
    assert all(item["match_score"] >= 60 for item in candidates)


def test_bitcoin_description_is_enough() -> None:
    candidates = discover_btc_symbols([symbol("CRYPTO1", "Bitcoin synthetic", "Crypto\\Misc")])
    assert len(candidates) == 1
    assert candidates[0]["match_score"] < 90


def test_non_btc_symbols_are_excluded() -> None:
    assert discover_btc_symbols([symbol("EURUSD", "Euro vs US Dollar", "Forex\\EURUSD")]) == []


def test_disabled_symbol_is_penalised() -> None:
    active = discover_btc_symbols([symbol("BTCUSDm", "Bitcoin", "Crypto")])[0]["match_score"]
    disabled = discover_btc_symbols([symbol("BTCUSDm", "Bitcoin", "Crypto", trade_mode=0)])[0]["match_score"]
    assert disabled < active


def test_is_btc_like() -> None:
    assert is_btc_like("BTCUSDm")
    assert is_btc_like("XBTUSD")
    assert is_btc_like("ABC", "Bitcoin index")
    assert not is_btc_like("ETHUSD", "Ethereum")


def test_pick_default_symbol_prefers_saved_symbol() -> None:
    candidates = [{"name": "BTCUSD"}, {"name": "BTCUSDm"}]
    assert pick_default_symbol(candidates, preferred="BTCUSDm") == "BTCUSDm"
    assert pick_default_symbol(candidates) == "BTCUSD"
    assert pick_default_symbol([]) is None
