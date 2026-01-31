"""Discord bot for Mealie recipe import"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

import sys
from pathlib import Path

# Add src to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings
from mealie.client import MealieClient
from mealie.models import RecipeValidationResult

logger = logging.getLogger(__name__)


class MealieBot(commands.Bot):
    """Discord bot for importing recipes to Mealie"""

    def __init__(self, settings: Settings):
        # Set up intents for slash commands
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True

        super().__init__(
            command_prefix=None,  # No prefix for slash commands
            intents=intents,
            help_command=None  # We'll implement our own help
        )

        self.settings = settings
        self.mealie_client: Optional[MealieClient] = None

    async def setup_hook(self):
        """Setup hook called before bot starts"""
        # Initialize Mealie client
        self.mealie_client = MealieClient(self.settings)
        await self.mealie_client.connect()

        # Register commands
        self._register_commands()

        # Sync slash commands with Discord
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} slash commands")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

        logger.info("Bot setup completed")

    async def close(self):
        """Cleanup when bot closes"""
        if self.mealie_client:
            await self.mealie_client.disconnect()
        await super().close()

    def _register_commands(self):
        """Register slash commands"""

        @self.tree.command(name="save_recipe", description="Zapisz przepis z podanego URL")
        @app_commands.describe(url="URL przepisu do zapisania")
        async def save_recipe(interaction: discord.Interaction, url: str):
            """Save a recipe from URL to Mealie"""
            # Don't await - create task and return immediately to keep command handler responsive
            asyncio.create_task(self._handle_save_recipe_slash(interaction, url))

        @self.tree.command(name="mealie_info", description="Pokaż informacje o bocie Mealie i dostępne komendy")
        async def mealie_info_command(interaction: discord.Interaction):
            """Show Mealie bot information and available commands"""
            logger.info(f"Slash command 'mealie_info' called by {interaction.user}")
            await self._handle_mealie_info_slash(interaction)

        # Handle messages - only process commands, no auto-detection
        @self.event
        async def on_message(message):
            if message.author == self.user:
                return

            logger.debug(f"Received message: '{message.content}' from {message.author}")
            # Only process commands, no automatic link detection
            await self.process_commands(message)

    async def _handle_save_recipe_slash(self, interaction: discord.Interaction, url: str):
        """Handle recipe saving for slash commands with AI fallback"""
        # Log immediately when command is received
        logger.info(f"[{interaction.id}] Received save_recipe command from {interaction.user}, deferring...")
        
        # CRITICAL: Defer IMMEDIATELY - Discord gives only 3 seconds to respond
        # This MUST be the first operation, before ANY other code
        try:
            await interaction.response.defer()
            logger.info(f"[{interaction.id}] Successfully deferred interaction")
        except discord.NotFound:
            # Interaction expired (404) - too late to respond
            logger.error(f"[{interaction.id}] Failed to defer: expired before defer (user: {interaction.user}, url: {url})")
            return
        except discord.HTTPException as e:
            # Other Discord API errors during defer
            logger.error(f"[{interaction.id}] Failed to defer: {e} (user: {interaction.user}, url: {url})")
            return
        
        # Defer successful - now process the recipe
        logger.info(f"[{interaction.id}] Starting recipe processing for URL: {url}")
        
        try:
            # Validate URL
            if not self._is_valid_url(url):
                await interaction.followup.send(
                    "❌ Nieprawidłowy URL. Upewnij się, że podajesz prawidłowy link do przepisu."
                )
                return

            # Step 1: Try to create recipe with Mealie parser
            embed = discord.Embed(
                title="🔄 Przetwarzanie przepisu...",
                description="Próba sparsowania przepisu przez Mealie...",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)

            try:
                recipe_data = await self.mealie_client.create_recipe_from_url(url)

                if recipe_data.get('status') == 'created' and recipe_data.get('slug'):
                    # Step 2: Validate if recipe has required components
                    is_valid, validation_reason = await self.mealie_client.validate_recipe_complete(recipe_data['slug'])

                    if is_valid:
                        # Recipe is complete - success!
                        recipe_url = self.mealie_client.get_recipe_url(recipe_data['slug'])
                        embed = discord.Embed(
                            title="✅ Przepis dodany pomyślnie!",
                            description="Przepis został prawidłowo sparsowany przez Mealie i zawiera wszystkie wymagane składniki.",
                            color=discord.Color.green()
                        )
                        embed.add_field(
                            name="🔗 Link do przepisu",
                            value=f"[Zobacz przepis]({recipe_url})",
                            inline=False
                        )
                        embed.add_field(
                            name="🏷️ Slug przepisu",
                            value=f"`{recipe_data['slug']}`",
                            inline=True
                        )
                        await interaction.followup.send(embed=embed)
                        return
                    else:
                        # Recipe created but incomplete - try AI parsing
                        logger.warning(f"Recipe created but incomplete: {validation_reason}")
                        embed = discord.Embed(
                            title="⚠️ Przepis sparsowany częściowo",
                            description=f"Mealie sparsował przepis, ale brakuje: {validation_reason}\n\n🔄 Próbuję sparsować przez AI...",
                            color=discord.Color.orange()
                        )
                        await interaction.followup.send(embed=embed)

                        # Step 3: Try AI parsing
                        ai_recipe_data = await self.mealie_client.parse_recipe_with_ai(url)

                        if ai_recipe_data:
                            # Create/update recipe with AI data
                            ai_slug = await self.mealie_client.create_recipe_from_ai_data(url, ai_recipe_data)

                            if ai_slug:
                                recipe_url = self.mealie_client.get_recipe_url(ai_slug)
                                embed = discord.Embed(
                                    title="🤖 Przepis sparsowany przez AI!",
                                    description="Przepis został pomyślnie sparsowany przez OpenAI i dodany do Mealie.",
                                    color=discord.Color.blue()
                                )
                                embed.add_field(
                                    name="🔗 Link do przepisu",
                                    value=f"[Zobacz przepis]({recipe_url})",
                                    inline=False
                                )
                                embed.add_field(
                                    name="🏷️ Slug przepisu",
                                    value=f"`{ai_slug}`",
                                    inline=True
                                )
                                embed.add_field(
                                    name="📝 Metoda",
                                    value="OpenAI parsing",
                                    inline=True
                                )
                                await interaction.followup.send(embed=embed)
                                return
                            else:
                                # AI parsing failed
                                embed = discord.Embed(
                                    title="❌ Parsowanie AI nie powiodło się",
                                    description="Nie udało się sparsować przepisu przez AI. Przepis może wymagać ręcznego dodania.",
                                    color=discord.Color.red()
                                )
                                await interaction.followup.send(embed=embed)
                                return
                        else:
                            # AI not available or failed
                            embed = discord.Embed(
                                title="❌ Brak wsparcia AI",
                                description="Przepis został częściowo sparsowany przez Mealie, ale brakuje wymaganych składników. AI nie jest dostępne lub nie udało się sparsować.",
                                color=discord.Color.red()
                            )
                            await interaction.followup.send(embed=embed)
                            return
                else:
                    # Mealie failed to create recipe - try AI
                    logger.warning("Mealie failed to create recipe - trying AI")
                    embed = discord.Embed(
                        title="⚠️ Mealie nie sparsował przepisu",
                        description="Mealie nie mógł sparsować tego przepisu.\n\n🔄 Próbuję sparsować przez AI...",
                        color=discord.Color.orange()
                    )
                    await interaction.followup.send(embed=embed)

                    # Try AI parsing
                    ai_recipe_data = await self.mealie_client.parse_recipe_with_ai(url)

                    if ai_recipe_data:
                        # Create recipe with AI data
                        ai_slug = await self.mealie_client.create_recipe_from_ai_data(url, ai_recipe_data)

                        if ai_slug:
                            recipe_url = self.mealie_client.get_recipe_url(ai_slug)
                            embed = discord.Embed(
                                title="🤖 Przepis sparsowany przez AI!",
                                description="Przepis został pomyślnie sparsowany przez OpenAI i dodany do Mealie.",
                                color=discord.Color.blue()
                            )
                            embed.add_field(
                                name="🔗 Link do przepisu",
                                value=f"[Zobacz przepis]({recipe_url})",
                                inline=False
                            )
                            embed.add_field(
                                name="🏷️ Slug przepisu",
                                value=f"`{ai_slug}`",
                                inline=True
                            )
                            embed.add_field(
                                name="📝 Metoda",
                                value="OpenAI parsing",
                                inline=True
                            )
                            await interaction.followup.send(embed=embed)
                            return
                        else:
                            # AI creation failed
                            embed = discord.Embed(
                                title="❌ Nie udało się utworzyć przepisu",
                                description="Zarówno Mealie jak i AI nie mogły sparsować tego przepisu. Spróbuj innego linku lub dodaj przepis ręcznie.",
                                color=discord.Color.red()
                            )
                            await interaction.followup.send(embed=embed)
                            return
                    else:
                        # AI not available or failed
                        embed = discord.Embed(
                            title="❌ Automatyczne parsowanie niemożliwe",
                            description="Zarówno Mealie jak i AI nie mogły sparsować tego przepisu. AI nie jest dostępne lub link może być nieprawidłowy.",
                            color=discord.Color.red()
                        )
                        await interaction.followup.send(embed=embed)
                        return

            except ValueError as ve:
                # Mealie parsing failed - try AI
                logger.warning(f"Mealie parsing failed: {ve}")
                embed = discord.Embed(
                    title="⚠️ Parsowanie przez Mealie nie powiodło się",
                    description="Mealie nie mógł sparsować tego przepisu.\n\n🔄 Próbuję sparsować przez AI...",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)

                # Try AI parsing
                ai_recipe_data = await self.mealie_client.parse_recipe_with_ai(url)

                if ai_recipe_data:
                    ai_slug = await self.mealie_client.create_recipe_from_ai_data(url, ai_recipe_data)

                    if ai_slug:
                        recipe_url = self.mealie_client.get_recipe_url(ai_slug)
                        embed = discord.Embed(
                            title="🤖 Przepis sparsowany przez AI!",
                            description="Przepis został pomyślnie sparsowany przez OpenAI i dodany do Mealie.",
                            color=discord.Color.blue()
                        )
                        embed.add_field(
                            name="🔗 Link do przepisu",
                            value=f"[Zobacz przepis]({recipe_url})",
                            inline=False
                        )
                        embed.add_field(
                            name="🏷️ Slug przepisu",
                            value=f"`{ai_slug}`",
                            inline=True
                        )
                        embed.add_field(
                            name="📝 Metoda",
                            value="OpenAI parsing",
                            inline=True
                        )
                        await interaction.followup.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="❌ Nie udało się utworzyć przepisu",
                            description="AI sparsował przepis, ale nie udało się go dodać do Mealie.",
                            color=discord.Color.red()
                        )
                        await interaction.followup.send(embed=embed)
                else:
                    embed = discord.Embed(
                        title="❌ Automatyczne parsowanie niemożliwe",
                        description="Zarówno Mealie jak i AI nie mogły sparsować tego przepisu.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=embed)

            except Exception as e:
                logger.error(f"Failed to process recipe from {url}: {e}")
                embed = discord.Embed(
                    title="❌ Błąd przetwarzania",
                    description=f"Wystąpił błąd podczas przetwarzania przepisu: {str(e)}",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Unexpected error in _handle_save_recipe_slash: {e}")
            # At this point interaction is already deferred, so always use followup
            try:
                await interaction.followup.send("❌ Wystąpił nieoczekiwany błąd.")
            except (discord.NotFound, discord.HTTPException) as send_error:
                # Interaction expired or Discord API error
                logger.error(f"Failed to send error message to Discord: {send_error}")

    async def _handle_mealie_info_slash(self, interaction: discord.Interaction):
        """Handle mealie_info command for slash commands"""
        embed = discord.Embed(
            title="🍳 Mealie Bot - Informacje",
            description="Bot do importowania przepisów z URL do aplikacji Mealie",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="📋 Dostępne komendy",
            value="""
/save_recipe [url] - Zapisz przepis z podanego URL
/mealie_info - Pokaż tę informację
            """,
            inline=False
        )

        embed.add_field(
            name="📝 Jak używać",
            value="1. Użyj `/save_recipe` i podaj URL przepisu\n2. Bot automatycznie pobierze i zapisze przepis w Mealie",
            inline=False
        )

        embed.add_field(
            name="🏷️ Tagowanie",
            value="Wszystkie przepisy są automatycznie tagowane jako:\n• **Discord Import**\n• **Verify** (do ręcznego sprawdzenia)",
            inline=False
        )

        embed.set_footer(text="Bot działa tylko na komendy slash - nie reaguje na zwykłe wiadomości z linkami")
        await interaction.response.send_message(embed=embed)

    async def _handle_save_recipe(self, ctx_or_message, url: str):
        """Handle recipe saving from either command or message"""
        try:
            # Send processing message
            processing_msg = await self._send_processing_message(ctx_or_message)

            # Validate URL
            if not self._is_valid_url(url):
                await self._send_error_message(
                    ctx_or_message,
                    "❌ Nieprawidłowy URL. Upewnij się, że podajesz prawidłowy link do przepisu."
                )
                return

            # Try to create recipe in Mealie
            try:
                recipe_data = await self.mealie_client.create_recipe_from_url(url)

                # Validate recipe data
                is_valid, reason = self.mealie_client.validate_recipe_data(recipe_data)

                if is_valid:
                    # Recipe created successfully
                    recipe_url = self.mealie_client.get_recipe_url(recipe_data.get('slug', ''))
                    await self._send_success_message(ctx_or_message, recipe_data, recipe_url)
                else:
                    # Recipe created but incomplete - try AI enhancement (future)
                    await self._send_partial_success_message(ctx_or_message, recipe_data, reason)

            except Exception as e:
                logger.error(f"Failed to create recipe from {url}: {e}")
                await self._send_error_message(
                    ctx_or_message,
                    f"❌ Nie udało się dodać przepisu. Błąd: {str(e)}"
                )

        except Exception as e:
            logger.error(f"Unexpected error in _handle_save_recipe: {e}")
            await self._send_error_message(
                ctx_or_message,
                "❌ Wystąpił nieoczekiwany błąd podczas przetwarzania przepisu."
            )

    async def _handle_help(self, ctx):
        """Handle help command"""
        help_text = """
**🤖 Mealie Discord Bot - Pomoc**

**Komendy:**
• `!mealie save_recipe <url>` - Zapisz przepis z podanego URL
• `!mealie help` - Pokaż tę pomoc

**Automatyczne wykrywanie:**
Bot automatycznie wykrywa linki do przepisów w wiadomościach i próbuje je zapisać.

**Przykład:**
```
!mealie save_recipe https://example.com/recipe
```
lub po prostu wyślij wiadomość z linkiem do przepisu.

**Tagi:**
Przepisy są automatycznie tagowane jako "Discord Import" i "Verify" do ręcznego sprawdzenia.
        """

        embed = discord.Embed(
            title="🍳 Mealie Bot - Pomoc",
            description=help_text,
            color=discord.Color.blue()
        )

        await ctx.send(embed=embed)

    def _extract_recipe_url(self, message_content: str) -> Optional[str]:
        """Extract recipe URL from message content"""
        # Simple regex for URL detection
        url_pattern = r'https?://[^\s<>"{}|\\^`[\]]+'
        urls = re.findall(url_pattern, message_content)

        # Return first URL if found
        return urls[0] if urls else None

    def _is_valid_url(self, url: str) -> bool:
        """Validate if URL is properly formatted"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    async def _send_processing_message(self, ctx_or_message) -> discord.Message:
        """Send processing message"""
        embed = discord.Embed(
            title="⚙️ Przetwarzanie przepisu...",
            description="Trwa dodawanie przepisu do Mealie. Proszę czekać...",
            color=discord.Color.orange()
        )

        if hasattr(ctx_or_message, 'send'):
            return await ctx_or_message.send(embed=embed)
        else:
            return await ctx_or_message.channel.send(embed=embed)

    async def _send_success_message(self, ctx_or_message, recipe_data: dict, recipe_url: str):
        """Send success message"""
        embed = discord.Embed(
            title="✅ Przepis dodany pomyślnie!",
            description=f"**{recipe_data.get('name', 'Przepis')}** został dodany do Mealie.",
            color=discord.Color.green()
        )

        embed.add_field(
            name="🔗 Link do przepisu",
            value=f"[Zobacz przepis]({recipe_url})",
            inline=False
        )

        embed.add_field(
            name="🏷️ Tagi",
            value=", ".join(recipe_data.get('tags', ['Brak tagów'])),
            inline=True
        )

        embed.set_footer(text="Przepis został oznaczony do weryfikacji")

        if hasattr(ctx_or_message, 'send'):
            await ctx_or_message.send(embed=embed)
        else:
            await ctx_or_message.channel.send(embed=embed)

    async def _send_partial_success_message(self, ctx_or_message, recipe_data: dict, reason: str):
        """Send partial success message for incomplete recipes"""
        embed = discord.Embed(
            title="⚠️ Przepis dodany częściowo",
            description=f"Przepis został dodany, ale brakuje niektórych elementów: {reason}",
            color=discord.Color.yellow()
        )

        recipe_url = self.mealie_client.get_recipe_url(recipe_data.get('slug', ''))
        embed.add_field(
            name="🔗 Link do przepisu",
            value=f"[Edytuj przepis]({recipe_url})",
            inline=False
        )

        if hasattr(ctx_or_message, 'send'):
            await ctx_or_message.send(embed=embed)
        else:
            await ctx_or_message.channel.send(embed=embed)

    async def _send_error_message(self, ctx_or_message, error_message: str):
        """Send error message"""
        embed = discord.Embed(
            title="❌ Błąd",
            description=error_message,
            color=discord.Color.red()
        )

        if hasattr(ctx_or_message, 'send'):
            await ctx_or_message.send(embed=embed)
        else:
            await ctx_or_message.channel.send(embed=embed)
