// The dev stack's identity provider: node-oidc-provider, configured to publish only what the app uses.
// Never deployed. A deployment signs in through the company's own provider.
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

import Provider from 'oidc-provider'

// Read settings from the environment the api shares, and refuse to start without one.
const required = (name) => {
  if (!process.env[name]) throw new Error(`${name} is not set`)
  return process.env[name]
}
// One origin for the browser, the api and the host, since every service shares the host's network.
const ISSUER = required('OIDC_ISSUER')

// Read beside this file, not the working directory.
const read = (name) => JSON.parse(readFileSync(new URL(name, import.meta.url), 'utf8'))

// The app's own client metadata, minus what this version does not implement.
// A statically configured client is validated strictly, so unknown fields would fail startup.
const UNIMPLEMENTED = ['frontchannel_logout_uri', 'frontchannel_logout_session_required']
const metadata = Object.fromEntries(
  Object.entries(read('./client.json')).filter(([key]) => !UNIMPLEMENTED.includes(key)),
)

// Every username is a person, so testing as someone else needs no setup.
const person = (username) => ({
  // Opaque and the same after every restart. The app keys users on it.
  sub: createHash('sha256').update(username).digest('hex').slice(0, 32),
  name: username,
  preferred_username: username,
  email: `${username}@example.com`,
  email_verified: true,
})

const provider = new Provider(ISSUER, {
  clients: [
    {
      client_id: required('OIDC_CLIENT_ID'),
      // No secret: the app proves itself with a key it publishes at its jwks_uri.
      ...metadata,
      subject_type: 'pairwise',
    },
  ],

  // Which claims each scope asks for.
  claims: {
    openid: ['sub'],
    email: ['email', 'email_verified'],
    profile: ['name', 'preferred_username'],
  },

  // Put those claims in the ID token. The app discards the access token, so it never calls userinfo.
  conformIdTokenClaims: false,

  features: {
    // The built-in login form. It never checks the password.
    devInteractions: { enabled: true },
    rpInitiatedLogout: {
      enabled: true,
      // Confirm sign-out without asking. The app proves the session with an id_token_hint
      // (RP-Initiated Logout §2).
      logoutSource(ctx, form) {
        const confirmed = form.replace(
          '</form>',
          '<input type="hidden" name="logout" value="yes"></form>',
        )
        ctx.body = `<!DOCTYPE html><html><body onload="document.forms[0].submit()">
          ${confirmed}<noscript><button type="submit" form="op.logoutForm">Sign out</button></noscript>
        </body></html>`
      },
    },
    // POST a logout token to the app, server to server.
    backchannelLogout: { enabled: true },
  },

  // Grant every sign-in without a consent screen. The app is the provider's own first party.
  async loadExistingGrant(ctx) {
    const existing =
      ctx.oidc.result?.consent?.grantId ?? ctx.oidc.session.grantIdFor(ctx.oidc.client.clientId)
    if (existing) return ctx.oidc.provider.Grant.find(existing)

    const grant = new ctx.oidc.provider.Grant({
      clientId: ctx.oidc.client.clientId,
      accountId: ctx.oidc.session.accountId,
    })
    grant.addOIDCScope(ctx.oidc.params.scope)
    await grant.save()
    return grant
  },

  // The account is the username typed at the login form.
  async findAccount(ctx, id) {
    return { accountId: id, claims: async () => person(id) }
  },

  // Hand out each user's opaque `sub`, not the username, which is their email.
  // The app keys users on `sub`, and an email can be reassigned.
  subjectTypes: ['pairwise'],
  async pairwiseIdentifier(ctx, accountId) {
    return person(accountId).sub
  },

  // Allow calls to localhost. The default refuses private addresses, which blocks back-channel logout.
  async fetch(url, options) {
    delete options.dispatcher
    return globalThis.fetch(url, options)
  },

  // Dev only. Sessions are in memory, so they end at every restart anyway.
  cookies: { keys: ['dev-idp-cookie-secret'] },
})

// Log failures. Back-channel logout has no browser in the path, so it is otherwise invisible.
provider.on('server_error', (ctx, err) => console.error('[dev-idp] server_error', err))
provider.on('backchannel.success', (ctx, client) =>
  console.log('[dev-idp] backchannel logout delivered to', client.clientId),
)
provider.on('backchannel.error', (ctx, err, client) =>
  console.error('[dev-idp] backchannel logout failed for', client.clientId, err.message),
)

// Listen on the issuer's port, so the two cannot disagree.
provider.listen(Number(new URL(ISSUER).port))
