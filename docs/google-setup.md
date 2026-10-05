# Connecting Google Calendar and Gmail

JARVIS uses your own Google Cloud project, so your data goes only between your computer and
Google. Setup takes about 10 minutes, once, and costs nothing.

## 1. Create a project

1. Open https://console.cloud.google.com/ and sign in with the Google account JARVIS should use.
2. Use the project picker at the top: **New project**, name it `JARVIS`, then **Create**.
   Make sure it's selected.

## 2. Turn on the two APIs

1. Go to **APIs & Services -> Library**.
2. Search for **Google Calendar API**, open it and click **Enable**.
3. Do the same for **Gmail API**.

## 3. Set up the sign-in screen

Google's console calls this either the **OAuth consent screen** or **Google Auth Platform**.

1. **Branding:** app name `JARVIS`, with your email as the support and developer contact.
2. **Audience:** user type **External**.
3. **Data access** (optional; JARVIS asks for these scopes anyway): add
   - `.../auth/calendar.events`
   - `.../auth/gmail.readonly`
   - `.../auth/gmail.compose`
4. **Audience -> Publish app**, so the status reads **In production**.

   This matters. While an app is in *Testing*, Google expires its sign-ins after 7 days, and
   JARVIS would ask you to reconnect every week. You don't need Google's app verification for
   your own use.

## 4. Create the client

1. Go to **Credentials** (or **Clients**): **Create credentials -> OAuth client ID**.
2. Choose application type **Desktop app**, name it `JARVIS desktop`, then **Create**.
3. **Download JSON** and save it as `~/.jarvis/google_client.json`. Then make it private:

   ```sh
   mv ~/Downloads/client_secret_*.json ~/.jarvis/google_client.json
   chmod 600 ~/.jarvis/google_client.json
   ```

Never put this file in the repo. It already lives outside it.

## 5. Sign in

```sh
scripts/start.sh google
```

Your browser opens Google's sign-in page:

1. Pick your account.
2. Google warns **"Google hasn't verified this app"**. That's expected for your own app: click
   **Advanced -> Go to JARVIS (unsafe)**.
3. Allow access to Calendar and Gmail.

The sign-in is saved in `~/.jarvis/google_token.json`, readable only by you. You can also
connect from the HUD or the chat by saying "connect Google".

## Try it

In the HUD or `scripts/start.sh chat`:

- "What's on my calendar tomorrow?"
- "Do I have unread email from Anna?"
- "Add lunch with Sam on Friday at 12:30." JARVIS asks you to approve first.
- "Draft a reply saying I'll be there." Drafts are never sent without asking.

## If something goes wrong

- **"Access blocked: JARVIS has not completed the Google verification process":** the app is
  still in Testing and your account isn't a test user. Publish it (step 3.4) or add yourself
  under **Audience -> Test users**.
- **"That Google API isn't enabled":** repeat step 2 for the API it names.
- **JARVIS says it lost access:** this happens if you revoked access, changed your password, or
  didn't use it for 6 months. Click **Connect Google** on the HUD, or run
  `scripts/start.sh google` again.
- **To disconnect:** remove JARVIS at https://myaccount.google.com/permissions and delete
  `~/.jarvis/google_token.json`.
