"""Signal Analyst: generates precise entry/SL/TP signals from live chart data.

This agent sits between the Trader and Risk Analysis. It uses the TradingView
live chart tools (get_live_candles, get_live_indicator, get_technical_analysis)
to produce a structured SignalAnalysis with precise price levels.
"""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SignalAnalysis, render_signal_analysis
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.agent_utils import (
    get_live_candles,
    get_live_indicator,
    get_technical_analysis,
    search_symbol,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_signal_analyst(llm):

    def signal_analyst_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        market_report = state.get("market_report", "")
        trader_plan = state.get("trader_investment_plan", "")

        tools = [
            get_live_candles,
            get_live_indicator,
            get_technical_analysis,
            search_symbol,
        ]

        system_message = (
            "You are a chart-reading signal analyst. Your job is to analyze live price "
            "data and technical indicators to produce precise entry, stop-loss, and "
            "take-profit levels for a trade.\n\n"
            "Workflow:\n"
            "1. Use search_symbol to find the correct TradingView symbol format (e.g. 'NASDAQ:AAPL')\n"
            "2. Use get_live_candles to retrieve recent price candles (try '1D' for daily, '60' for hourly)\n"
            "3. Use get_live_indicator to fetch RSI, MACD, or Supertrend values\n"
            "4. Use get_technical_analysis for TradingView's official TA summary\n\n"
            "Signal Rules:\n"
            "- **Buy**: Price above key moving averages, RSI recovering from oversold, bullish candle pattern, TA says Buy\n"
            "- **Sell**: Price below key MAs, RSI overbought, bearish pattern, TA says Sell\n"
            "- **Wait**: Mixed signals, choppy price action, no clear setup\n\n"
            "Level Rules:\n"
            "- **Entry**: Place at current close or a slight pullback to nearby support (for buy) / resistance (for sell)\n"
            "- **Stop Loss**: 1-2 ATR below the most recent swing low for buys, above swing high for sells\n"
            "- **Take Profit**: At least 2:1 reward-to-risk. Target the next major resistance (buy) or support (sell)\n"
            "- **Confidence**: 0.0-1.0 based on how many indicators agree. >0.7 means strong confluence\n\n"
            f"{instrument_context}\n"
            f"The trader has proposed this plan (use it for context): {trader_plan}\n"
            f"Market analysis so far: {market_report[:1000]}"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a chart-reading signal analyst producing entry/exit signals."
                    " Use the provided tools to fetch live chart and indicator data."
                    " You have access to: {tool_names}.\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([t.name for t in tools]))

        chain = prompt | llm.bind_tools(tools)

        # Loop through tool calls until the LLM stops requesting tools
        messages = state["messages"]
        result = chain.invoke(messages)

        while result.tool_calls:
            tool_results = []
            for tc in result.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                try:
                    tool_fn = next(t for t in tools if t.name == tool_name)
                    tool_output = tool_fn.invoke(tool_args)
                except Exception as e:
                    tool_output = f"Error: {e}"
                tool_results.append(
                    AIMessage(content=tool_output, tool_call_id=tc["id"])
                )
            messages = [result] + tool_results
            result = chain.invoke(messages)

        signal_report = result.content

        return {
            "messages": [result],
            "signal_report": signal_report,
            "sender": name,
        }

    return functools.partial(signal_analyst_node, name="Signal Analyst")
