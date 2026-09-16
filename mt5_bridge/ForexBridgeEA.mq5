//+------------------------------------------------------------------+
//|                                             ForexBridgeEA.mq5   |
//|  File-based bridge between this MT5 terminal and the local      |
//|  Python trading engine. See engine/bridge/protocol.py and       |
//|  MT5_SETUP.md for the full protocol description and install     |
//|  steps. Attach this EA to ONE chart (any symbol/timeframe --     |
//|  it manages its own symbol list from the input below) and       |
//|  leave "Allow Algo Trading" enabled.                             |
//|                                                                   |
//|  Design constraints this file deliberately respects:            |
//|   - No DLL imports (native macOS MT5 does not support them)     |
//|   - No sockets/pipes -- Common\Files only                       |
//|   - Only ever manages positions carrying MagicNumber, so it     |
//|     never touches trades you place manually or via another EA  |
//+------------------------------------------------------------------+
#property copyright "Forex Trading System"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include "Include/JsonBridge.mqh"

input string InpSymbols        = "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCHF,USDCAD,NZDUSD,XAUUSD";
input int    InpMagicNumber    = 990321;
input int    InpTimerSeconds   = 1;
input int    InpExportBarCount = 1000;
input int    InpSlippagePoints = 20;

CTrade trade;
string g_symbols[];
datetime g_last_bar_time[];

//+------------------------------------------------------------------+
int OnInit()
{
   BridgeEnsureFolders();
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);

   int n = StringSplit(InpSymbols, ',', g_symbols);
   ArrayResize(g_last_bar_time, n);
   for(int i = 0; i < n; i++)
   {
      StringTrimLeft(g_symbols[i]);
      StringTrimRight(g_symbols[i]);
      SymbolSelect(g_symbols[i], true);
      g_last_bar_time[i] = 0;
   }

   EventSetTimer(InpTimerSeconds);
   WriteHeartbeat();
   Print("ForexBridgeEA initialized. Bridge folder: Common\\Files\\", BRIDGE_ROOT);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   WriteHeartbeat();
   WriteAccount();
   for(int i = 0; i < ArraySize(g_symbols); i++)
   {
      WriteSymbol(g_symbols[i]);
      MaybeExportBars(i);
   }
   WritePositions();
   ProcessCommands();
}

//+------------------------------------------------------------------+
void WriteHeartbeat()
{
   string json = StringFormat("{\"time\": %d}", (int)TimeGMT());
   BridgeWriteText(HEARTBEAT_FILE_REL(), json);
}
string HEARTBEAT_FILE_REL() { return "heartbeat.json"; }

void WriteAccount()
{
   string json = StringFormat(
      "{\"login\": %d, \"broker\": \"%s\", \"currency\": \"%s\", \"balance\": %.2f, "
      "\"equity\": %.2f, \"margin\": %.2f, \"margin_free\": %.2f, \"leverage\": %d, \"server_time\": %d}",
      (int)AccountInfoInteger(ACCOUNT_LOGIN),
      JsonEscape(AccountInfoString(ACCOUNT_COMPANY)),
      AccountInfoString(ACCOUNT_CURRENCY),
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
      (int)TimeGMT()
   );
   BridgeWriteText("account.json", json);
}

string TradeModeString(ENUM_SYMBOL_TRADE_MODE mode)
{
   switch(mode)
   {
      case SYMBOL_TRADE_MODE_DISABLED:  return "DISABLED";
      case SYMBOL_TRADE_MODE_LONGONLY:  return "LONGONLY";
      case SYMBOL_TRADE_MODE_SHORTONLY: return "SHORTONLY";
      case SYMBOL_TRADE_MODE_CLOSEONLY: return "CLOSEONLY";
      default:                          return "FULL";
   }
}

void WriteSymbol(const string symbol)
{
   if(!SymbolInfoInteger(symbol, SYMBOL_SELECT))
      SymbolSelect(symbol, true);

   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);

   double margin_per_lot = 0.0;
   OrderCalcMargin(ORDER_TYPE_BUY, symbol, 1.0, ask, margin_per_lot);

   string json = StringFormat(
      "{\"digits\": %d, \"point\": %.10f, \"contract_size\": %.2f, \"tick_size\": %.10f, "
      "\"tick_value\": %.5f, \"volume_min\": %.2f, \"volume_max\": %.2f, \"volume_step\": %.2f, "
      "\"margin_initial_per_lot\": %.2f, \"trade_mode\": \"%s\", \"stops_level_points\": %d, "
      "\"freeze_level_points\": %d, \"currency_base\": \"%s\", \"currency_profit\": \"%s\", "
      "\"currency_margin\": \"%s\", \"swap_long\": %.2f, \"swap_short\": %.2f, "
      "\"bid\": %.5f, \"ask\": %.5f, \"quote_time\": %d}",
      (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS),
      SymbolInfoDouble(symbol, SYMBOL_POINT),
      SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE),
      SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE),
      SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE),
      SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN),
      SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX),
      SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP),
      margin_per_lot,
      TradeModeString((ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE)),
      (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL),
      (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL),
      SymbolInfoString(symbol, SYMBOL_CURRENCY_BASE),
      SymbolInfoString(symbol, SYMBOL_CURRENCY_PROFIT),
      SymbolInfoString(symbol, SYMBOL_CURRENCY_MARGIN),
      SymbolInfoDouble(symbol, SYMBOL_SWAP_LONG),
      SymbolInfoDouble(symbol, SYMBOL_SWAP_SHORT),
      bid, ask, (int)TimeGMT()
   );
   BridgeWriteText("symbols\\" + symbol + ".json", json);
}

void MaybeExportBars(int idx)
{
   string symbol = g_symbols[idx];
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, PERIOD_M5, 0, InpExportBarCount, rates);
   if(copied <= 0)
      return;

   // rates[0] is the currently-forming bar; only export CLOSED bars (index 1..copied-1)
   if(copied < 2)
      return;
   datetime newest_closed = rates[1].time;
   if(newest_closed == g_last_bar_time[idx])
      return; // nothing new since last export

   string content = "";
   for(int i = copied - 1; i >= 1; i--)
   {
      content += StringFormat("%d,%.5f,%.5f,%.5f,%.5f,%d\n",
         (int)rates[i].time, rates[i].open, rates[i].high, rates[i].low, rates[i].close, (int)rates[i].tick_volume);
   }
   BridgeWriteText("bars\\" + symbol + "_M5.csv", content);
   g_last_bar_time[idx] = newest_closed;
}

void WritePositions()
{
   string json = "{\"positions\": [";
   bool first = true;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue; // only report positions this EA/system opened

      string dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      if(!first)
         json += ",";
      first = false;
      json += StringFormat(
         "{\"ticket\": %d, \"symbol\": \"%s\", \"direction\": \"%s\", \"volume\": %.2f, "
         "\"entry_price\": %.5f, \"stop_loss\": %.5f, \"take_profit\": %.5f, \"open_time\": %d, \"profit\": %.2f}",
         (int)ticket, PositionGetString(POSITION_SYMBOL), dir, PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN), PositionGetDouble(POSITION_SL), PositionGetDouble(POSITION_TP),
         (int)PositionGetInteger(POSITION_TIME), PositionGetDouble(POSITION_PROFIT)
      );
   }
   json += "]}";
   BridgeWriteText(POSITIONS_FILE_REL(), json);
}
string POSITIONS_FILE_REL() { return "positions.json"; }

//+------------------------------------------------------------------+
//| Command processing                                               |
//+------------------------------------------------------------------+
void ProcessCommands()
{
   string search = BridgePath("commands") + "\\*.json";
   string filename;
   long handle = FileFindFirst(search, filename, FILE_COMMON);
   if(handle == INVALID_HANDLE)
      return;

   do
   {
      HandleCommandFile(filename);
   }
   while(FileFindNext(handle, filename));
   FileFindClose(handle);
}

void HandleCommandFile(const string filename)
{
   string content = BridgeReadText("commands\\" + filename);
   if(StringLen(content) == 0)
      return;

   string id = JsonGet(content, "id");
   string type = JsonGet(content, "type");
   string response = "";

   if(type == "ORDER")
      response = HandleOrderCommand(id, content);
   else if(type == "CLOSE")
      response = HandleCloseCommand(id, content);
   else if(type == "CLOSE_ALL")
      response = HandleCloseAllCommand(id);
   else
      response = StringFormat("{\"id\": \"%s\", \"status\": \"ERROR\", \"message\": \"Unknown command type\"}", id);

   BridgeWriteText("responses\\" + id + ".json", response);
   FileDelete(BridgePath("commands\\" + filename), FILE_COMMON);
}

string HandleOrderCommand(const string id, const string content)
{
   string symbol = JsonGet(content, "symbol");
   string direction = JsonGet(content, "direction");
   double volume = JsonGetDouble(content, "volume");
   double sl = JsonGetDouble(content, "sl");
   double tp = JsonGetDouble(content, "tp");
   string comment = JsonGet(content, "comment");

   if(!SymbolSelect(symbol, true))
      return StringFormat("{\"id\": \"%s\", \"status\": \"ERROR\", \"message\": \"Unknown symbol %s\"}", id, symbol);

   bool ok;
   double price = (direction == "BUY") ? SymbolInfoDouble(symbol, SYMBOL_ASK) : SymbolInfoDouble(symbol, SYMBOL_BID);

   if(direction == "BUY")
      ok = trade.Buy(volume, symbol, price, sl, tp, comment);
   else if(direction == "SELL")
      ok = trade.Sell(volume, symbol, price, sl, tp, comment);
   else
      return StringFormat("{\"id\": \"%s\", \"status\": \"ERROR\", \"message\": \"Invalid direction %s\"}", id, direction);

   if(!ok)
   {
      return StringFormat("{\"id\": \"%s\", \"status\": \"REJECTED\", \"message\": \"%s (retcode %d)\"}",
         id, JsonEscape(trade.ResultRetcodeDescription()), trade.ResultRetcode());
   }

   return StringFormat("{\"id\": \"%s\", \"status\": \"FILLED\", \"ticket\": %d, \"filled_price\": %.5f, \"message\": \"ok\"}",
      id, (int)trade.ResultOrder(), trade.ResultPrice());
}

string HandleCloseCommand(const string id, const string content)
{
   ulong ticket = (ulong)JsonGetLong(content, "ticket");
   if(!PositionSelectByTicket(ticket))
      return StringFormat("{\"id\": \"%s\", \"status\": \"ERROR\", \"message\": \"No open position with ticket %d\"}", id, (int)ticket);

   double closedVolume = PositionGetDouble(POSITION_VOLUME);
   bool ok = trade.PositionClose(ticket);
   if(!ok)
      return StringFormat("{\"id\": \"%s\", \"status\": \"ERROR\", \"message\": \"%s\"}", id, JsonEscape(trade.ResultRetcodeDescription()));

   return StringFormat("{\"id\": \"%s\", \"status\": \"FILLED\", \"ticket\": %d, \"filled_price\": %.5f, \"message\": \"closed %.2f lots\"}",
      id, (int)ticket, trade.ResultPrice(), closedVolume);
}

string HandleCloseAllCommand(const string id)
{
   string results = "";
   bool first = true;
   int total = PositionsTotal();
   // iterate backwards: closing shifts indices
   for(int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;

      bool ok = trade.PositionClose(ticket);
      if(!first)
         results += ",";
      first = false;
      if(ok)
         results += StringFormat("{\"ticket\": %d, \"status\": \"FILLED\", \"filled_price\": %.5f}", (int)ticket, trade.ResultPrice());
      else
         results += StringFormat("{\"ticket\": %d, \"status\": \"ERROR\", \"message\": \"%s\"}", (int)ticket, JsonEscape(trade.ResultRetcodeDescription()));
   }
   return StringFormat("{\"id\": \"%s\", \"status\": \"FILLED\", \"results\": [%s]}", id, results);
}
//+------------------------------------------------------------------+
