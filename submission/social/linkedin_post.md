# LinkedIn post

Tag: lablab.ai (@lablab.ai) and Alpaca (@Alpaca)

---

I spent this week building an autonomous options trading system for the Agentic Hackathon, hosted by lablab.ai on Alpaca's paper trading API — and I want to share the part that almost didn't make it into the pitch.

The architecture is five specialized agents, each with one narrow job: score momentum, propose trades, veto anything risky, execute only what's approved, report the results. A risk agent has hard veto authority over every order — the execution agent physically cannot bypass it; it raises an exception instead of submitting. Capital accounting is enforced with runtime assertions, not application logic that could quietly drift.

The backtest was rigorous: parameters fit on 2011–2018, checked once on 2019–2021, and the 2022–2026 window run exactly once and never touched again. Real earnings-drift signals from SEC EDGAR filings, not simulated data. +1072% on the out-of-sample test period, 1.88 Sharpe.

Then I deployed it live on paper trading — and all three option spread orders expired unfilled. The limit price was calculated from a model's own strikes and expiry, not the real listed contract Alpaca had on the books. A good backtest doesn't guarantee a working execution path, and this was the gap between them.

I traced it to four separate defects, fixed each one, and this morning — autonomously, with no human in the loop — the system sold its first real put credit spread and collected the premium.

That's the part I actually wanted to share: not the return number, but the six days between "the backtest looks great" and "it actually filled."

Built on Alpaca's paper trading API for the lablab.ai Agentic Hackathon.

🔗 Demo: https://momentum-options-agents-alexfeng3s-projects.vercel.app
💻 Code: https://github.com/alexfeng3/momentum-options-agents

#BuildInPublic #AgenticHackathon #AlgoTrading
