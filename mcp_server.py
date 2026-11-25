"""Small local-only stdio MCP entry point for the H00 portfolio release."""
from contextlib import redirect_stdout
import json
import sys

from aqwa_full_sea_batch import (get_h00_full_sea_batch, preview_h00_full_sea_batch,
                                read_h00_full_sea_batch, start_h00_full_sea_batch)
from demo import get_h00_replay_example

VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
SEA = {'hs_m':{'type':'number','minimum':.05,'maximum':5},
       'tp_s':{'type':'number','minimum':9,'maximum':16},
       'gamma':{'type':'number','minimum':1,'maximum':7},
       'direction_deg':{'type':'number','enum':[-180,-90,0,90,180]}}


def schema(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


CASES = {'type':'array','minItems':2,'maxItems':4,'items':schema({
    'case_name':{'type':'string','minLength':1,'maxLength':60},
    'sea_state':schema(SEA),
    'source_kind':{'type':'string','enum':['site_data','literature','research_assumption','commissioning']},
    'source_note':{'type':'string','minLength':3,'maxLength':240}})}
CHECKSUM = {'type':'string','pattern':'^[a-f0-9]{64}$'}
ID = {'type':'string','pattern':'^[a-f0-9]{32}$'}
ENTRY = (
    (get_h00_replay_example, {}, 'Read the offline synthetic example. Never runs AQWA.'),
    (preview_h00_full_sea_batch, {'cases':CASES}, 'Check 2–4 H00 seas against the private, pinned 19-point LINE database.'),
    (start_h00_full_sea_batch, {'cases':CASES,'expected_preview_sha256':CHECKSUM},
     'Start a previewed H00 batch in the locally licensed AQWA. Runs sequentially, without extrapolation.'),
    (get_h00_full_sea_batch, {'batch_id':ID}, 'Check progress of a native H00 batch.'),
    (read_h00_full_sea_batch, {'batch_id':ID}, 'Read the completed H00 batch and the report paths.'),
)
TOOLS = [{'name':f.__name__,'description':message,'inputSchema':schema(props),
          'annotations':{'readOnlyHint':not f.__name__.startswith('start_'),
                         'destructiveHint':False,'openWorldHint':False}}
         for f,props,message in ENTRY]
HANDLERS = {f.__name__:(f,props) for f,props,_ in ENTRY}


def tool_result(params, version):
    function, required = HANDLERS[params['name']]
    arguments = params.get('arguments', {})
    try:
        if not isinstance(arguments,dict) or arguments.keys() != required.keys():
            raise ValueError('Unexpected or missing tool arguments.')
        with redirect_stdout(sys.stderr):
            data = function(**arguments)
    except (OSError, ValueError, KeyError) as exc:
        return {'isError':True,'content':[{'type':'text','text':str(exc)}]}
    result = {'isError':False,'content':[{'type':'text','text':json.dumps(data,allow_nan=False)}]}
    if version in VERSIONS[:2]:
        result['structuredContent'] = data
    return result


def serve():
    version, initialized = None, False

    def respond(request_id, result=None, code=None, message=None):
        response = {"jsonrpc": "2.0", "id": request_id}
        if code is None:
            response["result"] = result
        else:
            response["error"] = {"code": code, "message": message}
        print(json.dumps(response), flush=True)

    for raw in sys.stdin.buffer:
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            respond(None, code=-32700, message="Parse error")
            continue
        if (not isinstance(request, dict) or request.get("jsonrpc") != "2.0"
                or not isinstance(request.get("method"), str)):
            respond(None, code=-32600, message="Invalid request")
            continue
        method, request_id = request["method"], request.get("id")
        if "id" not in request:
            if method == "notifications/initialized" and version:
                initialized = True
            continue
        params = request.get("params", {})
        if not isinstance(params, dict):
            respond(request_id, code=-32602, message="Invalid params")
        elif method == "ping":
            respond(request_id, {})
        elif method == "initialize":
            requested = params.get("protocolVersion")
            if not isinstance(requested, str) or version is not None:
                respond(request_id, code=-32602, message="Invalid initialize")
                continue
            version = requested if requested in VERSIONS else VERSIONS[0]
            respond(request_id, {"protocolVersion": version, "capabilities": {"tools": {}},
                                 "serverInfo": {"name": "aqwa-h00-mcp", "version": "0.1.0"}})
        elif not initialized:
            respond(request_id, code=-32002, message="Server not initialized")
        elif method == "tools/list":
            respond(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            if not any(tool["name"] == params.get("name") for tool in TOOLS):
                respond(request_id, code=-32602, message="Unknown tool")
                continue
            respond(request_id, tool_result(params, version))
        else:
            respond(request_id, code=-32601, message="Method not found")


if __name__ == '__main__':
    serve()
