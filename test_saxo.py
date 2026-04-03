from src.integrations.saxo_client import SaxoClient

client = SaxoClient()

spy = client.lookup_instrument("SPY")

payload = client.build_order_payload(
    uic=spy["Identifier"] if "Uic" not in spy and "Identifier" in spy else spy["Uic"],
    asset_type=spy["AssetType"],
    buy_sell="Buy",
    amount=1,
)

print("PAYLOAD:", payload)

result = client.simulate_order(payload)
print("SIMULATED ORDER RESULT:", result)