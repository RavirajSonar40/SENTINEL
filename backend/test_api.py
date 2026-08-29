if __name__ == "__main__":
    import urllib.request, json

    # Login
    data = json.dumps({"username": "admin", "password": "sentinel123"}).encode()
    req = urllib.request.Request("http://localhost:8000/auth/login", data=data, headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req).read())
    token = resp["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # List incidents
    req = urllib.request.Request("http://localhost:8000/incidents", headers=headers)
    incidents = json.loads(urllib.request.urlopen(req).read())
    print(f"Incidents: {len(incidents)}")
    for i in incidents:
        num = i["number"]
        title = i["title"]
        status = i["status"]
        source = i["source"]
        print(f"  INC-{num}: {title} [{status}] source={source}")
        if i.get("investigation"):
            inv = i["investigation"]
            print(f"    Investigation: {inv['status']} ({inv['progress_percent']}%)")

    # Test new incident creation
    data = json.dumps({
        "title": "Redis connection timeout",
        "description": "Redis connections timing out in production",
        "severity": "SEV-2",
        "service": "core-api-gateway",
        "source": "alert",
    }).encode()
    req = urllib.request.Request("http://localhost:8000/incidents", data=data, headers={**headers, "Content-Type": "application/json"})
    new_inc = json.loads(urllib.request.urlopen(req).read())
    print(f"\nCreated: INC-{new_inc['number']}: {new_inc['title']} [{new_inc['status']}]")

