//+------------------------------------------------------------------+
//|                                                  JsonBridge.mqh |
//|  Minimal, dependency-free helpers for the file-based bridge     |
//|  protocol described in engine/bridge/protocol.py.               |
//|                                                                  |
//|  MQL5 has no built-in JSON library and native macOS MT5 cannot  |
//|  import external DLLs, so this hand-rolled reader/writer is     |
//|  intentionally limited to the FLAT (non-nested) object shapes   |
//|  this project actually uses on both ends of the bridge -- it is |
//|  not a general-purpose JSON library.                            |
//+------------------------------------------------------------------+
#property strict

#define BRIDGE_ROOT "ForexTradingSystem"

//--- build a path under this terminal's own MQL5\Files\ForexTradingSystem
//--- folder (terminal-local, deliberately NOT the shared Common\Files folder
//--- -- see the note in engine/bridge/protocol.py)
string BridgePath(const string relative)
{
   return BRIDGE_ROOT + "\\" + relative;
}

//--- ensure the bridge folder tree exists (call once from OnInit)
void BridgeEnsureFolders()
{
   FolderCreate(BRIDGE_ROOT);
   FolderCreate(BridgePath("symbols"));
   FolderCreate(BridgePath("bars"));
   FolderCreate(BridgePath("commands"));
   FolderCreate(BridgePath("responses"));
}

//--- write a whole text file (overwrite) into MQL5\Files\...
bool BridgeWriteText(const string relative, const string content)
{
   int handle = FileOpen(BridgePath(relative), FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return false;
   FileWriteString(handle, content);
   FileClose(handle);
   return true;
}

//--- append a line to a text file, creating it if needed
bool BridgeAppendLine(const string relative, const string line)
{
   int handle = FileOpen(BridgePath(relative), FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return false;
   FileSeek(handle, 0, SEEK_END);
   FileWriteString(handle, line + "\n");
   FileClose(handle);
   return true;
}

//--- read a whole text file, "" if missing
string BridgeReadText(const string relative)
{
   int handle = FileOpen(BridgePath(relative), FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return "";
   string out = "";
   while(!FileIsEnding(handle))
      out += FileReadString(handle) + "\n";
   FileClose(handle);
   return out;
}

//--- JSON escape for a plain string value
string JsonEscape(const string s)
{
   string out = s;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   StringReplace(out, "\n", " ");
   StringReplace(out, "\r", "");
   return out;
}

//--- extract "key": <string-or-number-or-bareword> from a FLAT json object
string JsonGet(const string json, const string key)
{
   string pattern = "\"" + key + "\"";
   int pos = StringFind(json, pattern);
   if(pos < 0)
      return "";
   int colon = StringFind(json, ":", pos + StringLen(pattern));
   if(colon < 0)
      return "";
   int i = colon + 1;
   int len = StringLen(json);
   // skip whitespace
   while(i < len && (StringGetCharacter(json, i) == ' ' || StringGetCharacter(json, i) == '\t'))
      i++;
   if(i >= len)
      return "";
   if(StringGetCharacter(json, i) == '"')
   {
      int start = i + 1;
      int end = start;
      while(end < len && StringGetCharacter(json, end) != '"')
      {
         if(StringGetCharacter(json, end) == '\\')
            end++; // skip escaped char
         end++;
      }
      string raw = StringSubstr(json, start, end - start);
      StringReplace(raw, "\\\"", "\"");
      StringReplace(raw, "\\\\", "\\");
      return raw;
   }
   // number / true / false / null -- read until , or }
   int end = i;
   while(end < len && StringGetCharacter(json, end) != ',' && StringGetCharacter(json, end) != '}'
         && StringGetCharacter(json, end) != '\n' && StringGetCharacter(json, end) != ']')
      end++;
   string val = StringSubstr(json, i, end - i);
   StringTrimLeft(val);
   StringTrimRight(val);
   return val;
}

double JsonGetDouble(const string json, const string key, double def = 0.0)
{
   string v = JsonGet(json, key);
   if(v == "")
      return def;
   return StringToDouble(v);
}

long JsonGetLong(const string json, const string key, long def = 0)
{
   string v = JsonGet(json, key);
   if(v == "")
      return def;
   return StringToInteger(v);
}
