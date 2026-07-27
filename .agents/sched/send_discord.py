#!/usr/bin/env python3
import sys
import subprocess
import asyncio
import discord


def get_token() -> str:
    """Read Discord bot token from macOS Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "discord-bot-token",
             "-a", "opencode", "-w"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print("ERROR: Discord bot token not found in Keychain.", file=sys.stderr)
        sys.exit(1)


async def send_message(token: str, target: str, message: str) -> str:
    """Send a message to a Discord channel."""
    intents = discord.Intents.default()
    intents.message_content = True

    class SendBot(discord.Client):
        async def on_ready(self):
            # Parse "ServerName/channel" format
            parts = target.split("/", 1)
            if len(parts) == 2:
                server_name, channel_name = parts
                server_name = server_name.strip()
                channel_name = channel_name.strip()
                guild = discord.utils.find(
                    lambda g: g.name.lower() == server_name.lower(),
                    self.guilds
                )
                if not guild:
                    print(f"ERROR: Server '{server_name}' not found.", file=sys.stderr)
                    await self.close()
                    return
                channel = discord.utils.find(
                    lambda c: isinstance(c, discord.TextChannel)
                    and c.name.lower() == channel_name.lower(),
                    guild.channels
                )
                if not channel:
                    print(f"ERROR: Channel '{channel_name}' not found in '{server_name}'.",
                          file=sys.stderr)
                    await self.close()
                    return
                sent = await channel.send(message)
                print(f"Sent to #{channel.name} in {guild.name}")
            else:
                # Try as channel name across all guilds
                channel_name = parts[0].strip()
                channel = discord.utils.find(
                    lambda c: isinstance(c, discord.TextChannel)
                    and c.name.lower() == channel_name.lower(),
                    self.get_all_channels()
                )
                if not channel:
                    print(f"ERROR: Channel '{channel_name}' not found.", file=sys.stderr)
                    await self.close()
                    return
                sent = await channel.send(message)
                print(f"Sent to #{channel.name} in {channel.guild.name}")

            await self.close()

    bot = SendBot(intents=intents)
    await bot.start(token)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "学习星球/健身打卡"
    message = sys.stdin.read().strip()
    if not message:
        print("ERROR: No message provided on stdin.", file=sys.stderr)
        sys.exit(1)

    token = get_token()
    asyncio.run(send_message(token, target, message))


if __name__ == "__main__":
    main()
