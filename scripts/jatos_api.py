import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_BASE_URL = "http://127.0.0.1:9000"
API_PREFIX = "/jatos/api/v1"
WORKER_TYPES = {
    "gm": "GeneralMultiple",
    "pm": "PersonalMultiple",
    "gs": "GeneralSingle",
    "ps": "PersonalSingle",
    "mt": "MTurk",
}


def base_url():
    return os.environ.get("JATOS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def api_token():
    token = os.environ.get("JATOS_API_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        sys.exit("JATOS_API_TOKEN 未设置")
    return token


def api_request(method, path, body=None, content_type=None):
    url = base_url() + API_PREFIX + path
    headers = {
        "Authorization": "Bearer " + api_token(),
        "Accept": "application/json",
    }
    if content_type is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        sys.exit(json.dumps(
            {"error": "HTTPError", "status": error.code, "url": url, "body": detail},
            ensure_ascii=False,
            indent=2,
        ))
    except urllib.error.URLError as error:
        sys.exit(json.dumps(
            {"error": "URLError", "url": url, "reason": str(error.reason)},
            ensure_ascii=False,
            indent=2,
        ))
    if not raw:
        return {"status": status}
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"status": status, "body": text}


def json_request(method, path, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return api_request(method, path, body=body, content_type="application/json")


def study_identifier(args):
    study = args.study or os.environ.get("JATOS_STUDY_CODE")
    if not study:
        sys.exit("需要 --study，或设置 JATOS_STUDY_CODE（study id 或 uuid）")
    return study


def quote_study(study):
    return urllib.parse.quote(str(study), safe="")


def quote_asset_path(path):
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        sys.exit("资产路径必须是非空相对路径，且不能包含 ..")
    return "/".join(urllib.parse.quote(part, safe="") for part in parts)


def multipart_upload(file_path, field_name, filename):
    if not os.path.isfile(file_path):
        sys.exit("文件不存在：" + file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    boundary = "----MoyoJatos" + uuid.uuid4().hex
    with open(file_path, "rb") as handle:
        payload = handle.read()
    safe_filename = filename.replace('"', "_")
    head = (
        "--" + boundary + "\r\n"
        'Content-Disposition: form-data; name="' + field_name + '"; filename="' + safe_filename + '"\r\n'
        "Content-Type: " + content_type + "\r\n\r\n"
    ).encode("utf-8")
    tail = ("\r\n--" + boundary + "--\r\n").encode("utf-8")
    return head + payload + tail, "multipart/form-data; boundary=" + boundary


def command_create_study(args):
    payload = {
        "title": args.title,
        "active": True,
        "groupStudy": False,
        "linearStudy": False,
        "allowPreview": False,
    }
    if args.description is not None:
        payload["description"] = args.description
    return json_request("POST", "/studies", payload)


def command_upload_component_asset(args):
    study = study_identifier(args)
    remote_path = args.path or os.path.basename(args.file)
    filename = args.filename or os.path.basename(args.file)
    body, content_type = multipart_upload(args.file, "studyAssetsFile", filename)
    path = "/studies/" + quote_study(study) + "/assets/" + quote_asset_path(remote_path)
    return api_request("POST", path, body=body, content_type=content_type)


def command_create_component(args):
    study = study_identifier(args)
    payload = {
        "title": args.title,
        "active": True,
        "reloadable": args.reloadable,
    }
    if args.html_file is not None:
        payload["htmlFilePath"] = args.html_file
    if args.comments is not None:
        payload["comments"] = args.comments
    if args.component_input is not None:
        try:
            payload["componentInput"] = json.loads(args.component_input)
        except json.JSONDecodeError as error:
            sys.exit("--component-input 不是合法 JSON：" + str(error))
    return json_request("POST", "/studies/" + quote_study(study) + "/components", payload)


def command_create_study_code(args):
    study = study_identifier(args)
    payload = {"type": WORKER_TYPES[args.type]}
    if args.amount is not None:
        payload["amount"] = args.amount
    if args.comment is not None:
        payload["comment"] = args.comment
    return json_request("POST", "/studies/" + quote_study(study) + "/studyCodes", payload)


def build_parser():
    parser = argparse.ArgumentParser(
        description="JATOS 3.11.3 本地开发 API 客户端；认证使用 JATOS_API_TOKEN，"
                    "study 使用 JATOS_STUDY_CODE 作为默认值（study id 或 uuid）。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_study = subparsers.add_parser("create-study", help="创建 study")
    create_study.add_argument("--title", required=True)
    create_study.add_argument("--description")
    create_study.set_defaults(func=command_create_study)

    upload_asset = subparsers.add_parser(
        "upload-component-asset",
        help="上传文件到 study assets（JATOS 组件通过 htmlFilePath 引用）",
    )
    upload_asset.add_argument("--study")
    upload_asset.add_argument("--file", required=True)
    upload_asset.add_argument("--path", help="study assets 内的相对路径，默认使用本地文件名")
    upload_asset.add_argument("--filename", help="multipart 中使用的文件名，默认使用本地文件名")
    upload_asset.set_defaults(func=command_upload_component_asset)

    create_component = subparsers.add_parser("create-component", help="在 study 中创建 HTML 组件")
    create_component.add_argument("--study")
    create_component.add_argument("--title", required=True)
    create_component.add_argument("--html-file", help="相对于 study assets 根目录的 HTML 路径")
    create_component.add_argument("--comments")
    create_component.add_argument("--reloadable", action="store_true")
    create_component.add_argument("--component-input", help="JSON 字符串，写入 componentInput")
    create_component.set_defaults(func=command_create_component)

    create_code = subparsers.add_parser("create-study-code", help="生成 publix 链接使用的 study code")
    create_code.add_argument("--study")
    create_code.add_argument("--type", required=True, choices=sorted(WORKER_TYPES))
    create_code.add_argument("--amount", type=int)
    create_code.add_argument("--comment")
    create_code.set_defaults(func=command_create_study_code)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
