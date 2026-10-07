# Market Maker

An interactive market-making game built with Flask, SQLite, plain JavaScript and Chart.js.

**Live demo:** https://market-maker-i1ez.onrender.com

## 1. What This Project Is

This is a market-making game. The player acts as a market maker. Each game has a hidden true value V, drawn from a normal distribution with a mean of 100 and a standard deviation of 10, and lasts 20 rounds. In each round, you submit both a bid and an ask. A random trader then arrives and may buy at your ask, sell at your bid, or choose not to trade. After 20 rounds, your inventory is settled at V, and your final profit or loss becomes your score.

The game demonstrates "adverse selection": 40% of traders are informed. They know V and only trade when it benefits them. For example, if V is higher than your ask, they will buy. This means the traders who accept your quotes are more likely to cause you losses. You can see the direction of each trade, but you cannot see whether the trader was informed. You have to infer information from the trading history and protect yourself by widening your bid-ask spread.

All game parameters (informed probability, noise, inventory cap, number of rounds) are defined in one block at the top of `game_logic.py`.

## 2. How to Play

1. Enter a name (optional, up to 20 characters) and click **Start**.
2. Each round, enter a bid and an ask (the bid must be lower than the ask), then click **Submit quote**.
3. The page describes what happened that round in one sentence and adds a row to the history table.
4. The first chart shows your bid and ask as two lines, with markers on rounds where trades occurred. Buy and sell markers have different shapes. The second chart shows your estimated profit or loss together with your inventory. Because V is hidden until the end, the estimate marks your inventory at the average of past trade prices (100 if there are none).
5. You can click **End game early** at any time, with a confirmation step. Games ended early do not appear on the leaderboard.
6. After all 20 rounds, the results screen reveals V and your final profit or loss. It also breaks down your profit or loss from informed and uninformed traders, highlights the rounds with informed traders, and displays the top 10 leaderboard entries.

## 3. Features I Am Most Proud Of

- **Keeping the true value hidden until the game ends:** I chose this feature because V and each trader's informed status stay on the server and are not sent to the browser through the API until the game ends. Players have to reason from the trading history instead of using developer tools to look up the answer.
- **Breaking down profit and loss after the game:** I chose this feature because the results screen separately shows profit or loss from informed and uninformed traders and reveals each round's trader type. This lets players review how information asymmetry affected their results.
- **Only ranking games that complete all 20 rounds:** I chose this feature because I noticed that ending a game after zero rounds gives a score of 0, which could rank above players who completed the game but lost money. I decided that only games completing all 20 rounds should qualify, making scores more comparable.

## 4. How to Run Locally

```bash
git clone https://github.com/david555787/market-maker.git
cd market-maker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

I used Python 3.12. The SQLite database file is created automatically the first time the app starts. The default port is 5000. On Macs, AirPlay often uses port 5000, so I changed `PORT` to `5001` in my local `.env` file and opened http://localhost:5001. To run the tests, use `python -m pytest -v`. There are 160 tests in total. On Render the app is started with gunicorn (see `Procfile`).

## 5. How Secrets and Configuration Are Handled

This project does not use any third-party API keys. The configurable settings are `SECRET_KEY`, `DB_PATH`, `FLASK_DEBUG`, and `PORT`. They are all read from environment variables in `config.py`. If `SECRET_KEY` is not set, `config.py` falls back to a placeholder value meant only for local development; the real value is set only on Render.

Locally, I use a `.env` file, which is excluded by `.gitignore`, along with `*.db` and `venv/`. The repository only includes `.env.example` as a template. On Render, I set `SECRET_KEY` through the dashboard's Environment Variables settings. Render provides `PORT`, so I do not need to set it myself.

## 6. Mobile or Desktop

I mainly tested this game on desktop. I played several games locally and one game on the deployed Render website, but I have not tested it at phone widths. The interface uses a single-column layout on small screens, 16px input text, and buttons at least 48px tall, and tables scroll horizontally inside their containers, but I have not verified the actual mobile experience.

## 7. Known Limitations

- On Render's free tier, the database is cleared whenever the service is redeployed or restarted, so the leaderboard resets.
- Render's free service sleeps after a period of inactivity, so opening the site for the first time may take about a minute.
- The inventory cap (10), trade size (1), and default mark price (100) are defined separately in both `game_logic.py` and `app.js`. Changes to these rules must be synchronized between the two files.
- The frontend has no automated tests, only a manual testing checklist.
- The id of an unfinished game is kept in the browser's localStorage, so clearing browser data loses that game.
- Leaderboard names are typed in by the player; there are no accounts.

## 8. How I Used AI

I used one long conversation in the Claude app to help write the game logic, database layer, API, tests, and frontend. Keeping everything in one conversation helped preserve the project context and keep the implementation consistent with the same rules. Claude could not directly access my files, so I copied its generated code into the project, ran it myself, and sent back error messages. I used a separate Claude conversation to understand the assignment, plan the development steps, prepare prompts, and troubleshoot terminal, Git, and Render issues. The full prompts and my notes on each step are in `prompt_log.md`.

After the main code was written, I made three small changes to the project with help from that second conversation:

- **Theme:** I decided the interface should be black and red. The second conversation suggested the color values for the `:root` variables in `style.css`, and I applied them and checked the result in the browser.
- **Negative profit in red:** I used `grep` to check whether anything colored negative profit and found that nothing did. The second conversation suggested a small `showPnl` function that toggles a `negative` class, plus a CSS rule; I added them and replaced the four calls that display profit and loss.
- **Game rule:** I changed the informed-trader probability from `0.3` to `0.4` in `game_logic.py`. The tests still passed because the relevant test compares the observed proportion against the `INFORMED_PROBABILITY` constant rather than a hardcoded `0.3`. I renamed that test so its name matches what it checks.

One mistake AI made was writing two tests that asserted an uninformed trader could only "buy" or only "sell." However, its implementation first randomly chooses a buy or sell direction and then checks whether the quote is attractive, so "no trade" is also a possible outcome. I read the test failure messages and compared them with the trading rules. After identifying that the assertions had left out the "no trade" case, I changed them myself to check that the wrong trade direction never occurred and the expected trade direction did occur.