function base64urlToBytes(base64url) {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4)
  const base64 = (base64url + pad).replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(base64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes
}

function bytesToBase64url(buffer) {
  const bytes = new Uint8Array(buffer)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function decodeRegistrationOptions(options) {
  return {
    ...options,
    challenge: base64urlToBytes(options.challenge),
    user: options.user
      ? { ...options.user, id: base64urlToBytes(options.user.id) }
      : undefined,
    excludeCredentials: (options.excludeCredentials || []).map((c) => ({
      ...c,
      id: base64urlToBytes(c.id),
    })),
  }
}

function decodeAuthenticationOptions(options) {
  return {
    ...options,
    challenge: base64urlToBytes(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c) => ({
      ...c,
      id: base64urlToBytes(c.id),
    })),
  }
}

function encodeRegistrationCredential(cred) {
  return JSON.stringify({
    id: cred.id,
    rawId: bytesToBase64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment,
    clientExtensionResults: cred.getClientExtensionResults?.() ?? {},
    response: {
      clientDataJSON: bytesToBase64url(cred.response.clientDataJSON),
      attestationObject: bytesToBase64url(cred.response.attestationObject),
      transports: cred.response.getTransports?.() ?? [],
    },
  })
}

function encodeAuthenticationCredential(cred) {
  return JSON.stringify({
    id: cred.id,
    rawId: bytesToBase64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment,
    clientExtensionResults: cred.getClientExtensionResults?.() ?? {},
    response: {
      clientDataJSON: bytesToBase64url(cred.response.clientDataJSON),
      authenticatorData: bytesToBase64url(cred.response.authenticatorData),
      signature: bytesToBase64url(cred.response.signature),
      userHandle: cred.response.userHandle
        ? bytesToBase64url(cred.response.userHandle)
        : null,
    },
  })
}

export const webauthn = {
  isSupported() {
    return (
      typeof window !== 'undefined' &&
      typeof window.PublicKeyCredential !== 'undefined' &&
      typeof navigator !== 'undefined' &&
      navigator.credentials &&
      typeof navigator.credentials.create === 'function'
    )
  },

  async createCredential(options) {
    const publicKey = decodeRegistrationOptions(options)
    const cred = await navigator.credentials.create({ publicKey })
    if (!cred) throw new Error('Passkey creation was cancelled')
    return encodeRegistrationCredential(cred)
  },

  async getCredential(options) {
    const publicKey = decodeAuthenticationOptions(options)
    const cred = await navigator.credentials.get({ publicKey })
    if (!cred) throw new Error('Passkey authentication was cancelled')
    return encodeAuthenticationCredential(cred)
  },
}
