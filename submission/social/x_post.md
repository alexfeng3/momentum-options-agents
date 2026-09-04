# X / Twitter post

Tag by typing the handles directly in the post — X auto-links them:
**@lablabai** · **@AlpacaHQ**

---

## Short version (275 chars — fits the classic 280 limit, no link)

Built 5 autonomous trading agents for the @lablabai x @AlpacaHQ Agentic Hackathon. 1 risk agent has veto power over every order.

Backtest looked great. Live: all 3 option orders expired unfilled. Found the bug, fixed it — today it sold its first real spread.

#BuildInPublic

*Add the demo/GitHub link as a reply to this post, or paste it in and let X shorten it — either drops you slightly over 280 unless your account has the extended post length.*

---

## Longer version (731 chars — needs X Premium / extended post length)

Building an autonomous options trading system for the Agentic Hackathon on @AlpacaHQ paper trading, hosted by @lablabai.

5 agents. 1 risk officer with hard veto power. Capital math that structurally can't double-spend.

Backtest: 2022–26 test period, run once, never re-tuned. +1072% return, 1.88 Sharpe.

Then I shipped it live — and all 3 option orders expired unfilled. The limit price was calculated off a model's own strikes, not the real listed contract. Classic backtest-to-live gap.

Found it, fixed 4 bugs, and this morning it sold its first real put credit spread and collected the premium — autonomously, no human in the loop.

Backtests are cheap. Real fills aren't.

🔗 https://momentum-options-agents-alexfeng3s-projects.vercel.app
💻 https://github.com/alexfeng3/momentum-options-agents

#BuildInPublic
