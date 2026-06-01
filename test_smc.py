import sys, os
os.environ["SMC_CREDIT"] = "0"
sys.path.insert(0, ".")

from run_us100_monitor import get_candles
from smc_analysis import analyze_smc, fmt

m15 = get_candles("CFI:US100", "15", 50)
m5 = get_candles("CFI:US100", "5", 40)
m1 = get_candles("CFI:US100", "1", 60)

print(f"Candles: 15M={len(m15)}, 5M={len(m5)}, 1M={len(m1)}")

sig = analyze_smc(m15, "15M", m5, m1)
print(f"\nSMC signals found: {len(sig)}")
print("=" * 60)

for s in sig:
    print(f"  {s['direction']:6s} | {s['setup']:35s} | cf={s['confidence']:.0%}")
    print(f"         Entry: {fmt(s['entry'])}  SL: {fmt(s['sl'])}  TP: {fmt(s['tp'])}")
    print(f"         {s['reasoning'][:120]}")
    print()

if not sig:
    print("No SMC signals — market quiet or closed. Will fire when price moves.")
