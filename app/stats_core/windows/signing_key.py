"""Public Ed25519 key used to verify official production update manifests.

The matching private key is never stored in the repository or shipped to
customer devices. It is stored only as the GitHub Actions secret
UPDATE_SIGNING_PRIVATE_KEY.
"""

UPDATE_SIGNING_PUBLIC_KEY_B64 = "5BKW4eUps39+GhTRnHHzqGz03VNembdmaYBoqagzqr4="
