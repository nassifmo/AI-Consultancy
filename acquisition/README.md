# Collecting company API extracts

This reusable collector reads an approved JSON REST endpoint using GET requests. A company-specific configuration selects the records field, pagination rule and query filters. The output is a local `source/records.jsonl` file that the pilot mapping layer can normalize, plus a manifest with input settings, page hashes, row counts and the content hash of the output. Original record identifiers and duplicate records are preserved.

The sample URL uses the reserved `example.invalid` domain. Replace it with the company's authorized endpoint after reviewing its documented response, access scope, pagination and history retention. Validate a configuration without making requests from the shipment benchmark directory:

```powershell
.venv/Scripts/python.exe -m acquisition --config acquisition/example_config.json --check-config
```

The credential belongs in the environment variable named in `credential_env`. An authorized collection then runs with:

```powershell
.venv/Scripts/python.exe -m acquisition --config approved-source.json --output collections
```

The three supported pagination modes are `none`, `next_url`, and `offset`. `next_url` requires the configured next-page field on every response, with an explicit null or empty value on the last page. Offset mode requires an explicit `empty` or `short_page` completion rule matching the provider's documentation. Use overlapping update filters for repeat extracts when the source can deliver late revisions, then let the mapping and verification stages inspect the stable source IDs. The collector publishes a bundle only after the selected extraction reaches its configured endpoint. A failed page leaves no successful collection or persisted checkpoint. Repeating identical source pages and configuration returns the same verified bundle.

Page and data limits stop incomplete extractions. Retries apply to connection failures, HTTP 429 and server errors. Requests honor the server's Retry-After wait when it fits the configured maximum. A longer wait stops the collection with an instruction to run again later. Requests use timeouts, HTTPS for bearer credentials and same-origin redirects and pagination. Access tokens are excluded from artifacts. The collector rejects payloads that echo its own credential. [Requests timeout and response streaming documentation](https://requests.readthedocs.io/en/latest/user/advanced/)

The collector's own session disables implicit environment authentication and proxy configuration. A company client requiring a proxy, custom trust certificate or another approved authentication method can supply a configured session to the Python API. Confirm that configuration against the company's access requirements.

Completion describes the configured extraction. Source owners still need to confirm that the account can see the required rows and fields, including corrections and deletions, that the selected study interval is covered, and that logging and history were retained. Schema mapping and evaluation remain separate stages. No company endpoint or credentials have been supplied or tested.
