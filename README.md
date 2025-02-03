# BullyBot
This is a discord bot created to help with scheduling matches and events via discord automatically 
## SETUP
This bot is created via python and requires an up to date installation in order to function properly. You must also install a few requirements provided through Discord's API. Input the commands below: <br/> <br/>
pip install -U py-cord <br/>
pip install -U discord-py-interactions <br/>
pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib <br/><br/>

You must setup a .env file in order to use your corresponding token to your bot. <br/>
pip install python-dotenv <br/>
Then create a file title .env and store your bot token inside the variable "MY_TOKEN" <br/><br/>
## COMMANDS
The bot contains a variety of commands for both admins and generic users.<br/>
- /Book (Contains an interactive menu for users to schedule a future match date.)
- /Remove (Allows the user to select a pre-existing match for deletion.)
- /Schedule (Displays an interactive calendar, allowing the user to view upcoming matches)
- /Dump (Allows an admin to forcefully remove all matches existing in the current database)
- /Rosters (Upon selecting a game, displays all users currently assigned to that titles teams)
- /Credits (Displays information regarding the creator as well as some basic info on commands/functionality)
  <br/><br/>
# HOW IT WORKS
The bot displays an interactive menu for users to select a date, time, # of setups, game title, and finally their corresponding tier of team.<br/>
Upon completion, the bot pushes the data to a JSON file stored locally before pushing to a Google Drive folder held online.<br/>
Upon running the schedule or remove commands, the local JSON is updated via the Google Drive to maintain an accurate schedule.<br/>
Commands such as rosters searches through every user in the server and creates a list based on their current assigned roles.<br/>
Finally, the bot is constantly held on a Raspberry Pi that is also used for other misc scripts under MSU Esports.
