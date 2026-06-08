# Readest Self-host Client Configuration

Readest desktop and mobile clients can be pointed at a compatible self-hosted backend by entering one public server base URL in the client.

The client does not contain a private backend URL. Each user supplies their own server URL at runtime.

## Server URL

In the desktop or mobile app, open the login page or Settings -> Server, then enter a server base URL such as:

```text
https://your-readest-server.example.com
```

The client normalizes the URL before saving it:

- leading and trailing whitespace is removed
- trailing slashes are removed
- only `http` and `https` URLs are accepted
- production builds require `https`
- development builds may use `http` for localhost, loopback, or local network testing

## Public Runtime Config Endpoint

A self-hosted server should expose one of these public endpoints:

```text
GET /.well-known/readest-client-config.json
```

or:

```text
GET /api/public/runtime-config
```

The `.well-known` endpoint is tried first. If that request fails, the client tries `/api/public/runtime-config`.

Example response:

```json
{
  "apiBaseUrl": "https://your-readest-server.example.com",
  "supabaseUrl": "https://your-supabase-public.example.com",
  "supabaseAnonKey": "your-public-anon-key"
}
```

Fields:

- `apiBaseUrl`: public base URL for Readest API requests. If omitted, the entered server base URL is used.
- `supabaseUrl`: public Supabase project URL used by the client for authentication and sync.
- `supabaseAnonKey`: Supabase public anon key. This is not the service role key.

Current Readest authentication and sync flows require Supabase client config, so `supabaseUrl` and `supabaseAnonKey` must be present for a saved custom server.

## Public Config Is Not Secret Config

The runtime config endpoint is public client configuration. It must only return values that are safe for an installed app or browser client to see.

Never return server-side secrets from this endpoint, including:

- Supabase `service_role` keys
- JWT signing secrets
- database URLs or database passwords
- S3 or object storage secrets
- AWS secret access keys
- Tauri updater private keys
- Android keystores or signing passwords
- SSH keys or other private keys

The client rejects runtime config responses that contain common dangerous secret field names.

## Manual Configuration

The recommended setup is to expose one of the public runtime config endpoints and ask users to enter only the server base URL.

If a deployment cannot expose that endpoint, an advanced manual mode may be added later for entering `apiBaseUrl`, `supabaseUrl`, and `supabaseAnonKey` directly. The default client flow intentionally avoids asking users to handle multiple backend values.

## Session Handling

When the saved server changes, the client clears local authentication session data and requires the user to sign in again. This prevents a session from one server from being reused against another server.

## Public Fork Boundary

For public forks and GitHub Actions:

- do not commit real deployment URLs, service keys, database credentials, signing keys, Android keystores, or private updater keys
- keep Tauri updater private keys in GitHub Actions secrets only
- keep Android signing material in GitHub Actions secrets only
- use the fork's public GitHub Releases `latest.json` for updater metadata, not the official Readest updater endpoint

