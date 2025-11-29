"""Mealie API client for recipe management"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from config.settings import Settings

logger = logging.getLogger(__name__)


class MealieClient:
    """Client for interacting with Mealie API"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.mealie_base_url
        self.api_token = settings.mealie_api_token
        self.session: Optional[aiohttp.ClientSession] = None

        # Headers for API requests
        self.headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # Timeout for recipe processing (Mealie can take time to scrape recipes)
        self.timeout = aiohttp.ClientTimeout(total=60)  # 60 seconds timeout

    def _get_default_tags(self) -> List[str]:
        """Get default tags as list from comma-separated string"""
        if isinstance(self.settings.default_recipe_tags, str):
            return [tag.strip() for tag in self.settings.default_recipe_tags.split(',') if tag.strip()]
        elif isinstance(self.settings.default_recipe_tags, list):
            return self.settings.default_recipe_tags
        else:
            return ["Discord Import", "Verify"]

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()

    async def connect(self):
        """Initialize HTTP session"""
        if self.session is None:
            self.session = aiohttp.ClientSession(headers=self.headers, timeout=self.timeout)

    async def disconnect(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def create_recipe_from_url(self, recipe_url: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create a recipe in Mealie by parsing a URL

        Args:
            recipe_url: URL of the recipe to import
            tags: Optional list of tags to add to the recipe

        Returns:
            Recipe data from Mealie API

        Raises:
            aiohttp.ClientError: If API request fails
            ValueError: If recipe creation fails
        """
        if not self.session:
            await self.connect()

        # Prepare request data
        request_data = {
            'url': recipe_url,
            'tags': tags or self._get_default_tags()
        }

        endpoint = f"{self.base_url}/api/recipes/create/url"

        try:
            async with self.session.post(endpoint, json=request_data) as response:
                response_text = await response.text()

                if response.status == 201 or response.status == 200:
                    # Mealie returns recipe slug/ID as string, not JSON object
                    if response_text.startswith('"') and response_text.endswith('"'):
                        # Valid recipe slug/ID returned
                        recipe_slug = response_text.strip('"')
                        logger.info(f"Successfully created recipe from URL: {recipe_url}, slug: {recipe_slug}")

                        # Try to add tags to the created recipe
                        try:
                            await self._add_tags_to_recipe(recipe_slug, self._get_default_tags())
                            logger.info(f"Added default tags to recipe: {recipe_slug}")
                        except Exception as tag_error:
                            logger.warning(f"Failed to add tags to recipe {recipe_slug}: {tag_error}")

                        # Return recipe info with slug
                        return {
                            'slug': recipe_slug,
                            'url': recipe_url,
                            'status': 'created'
                        }
                    elif response_text.startswith('"no-recipe'):
                        # Could not extract recipe
                        raise ValueError(f"Could not extract recipe from URL: {response_text}")
                    else:
                        # Unexpected response format
                        raise ValueError(f"Unexpected response format: {response_text}")
                elif response.status == 400:
                    # Bad request - invalid URL or format
                    raise ValueError(f"Invalid recipe URL or format: {response_text}")
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create recipe. Status: {response.status}, Method: {response.method}, URL: {response.url}")
                    logger.error(f"Request data: {request_data}")
                    logger.error(f"Response headers: {dict(response.headers)}")
                    logger.error(f"Error: {error_text}")
                    raise ValueError(f"Failed to create recipe: {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error while creating recipe: {e}")
            raise

    async def validate_recipe_complete(self, recipe_slug: str) -> tuple[bool, str]:
        """
        Validate if recipe has all required components (ingredients and instructions)

        Args:
            recipe_slug: Recipe slug to validate

        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            recipe_data = await self.get_recipe(recipe_slug)

            # Check if recipe has ingredients
            ingredients = recipe_data.get('recipeIngredient', [])
            has_ingredients = len(ingredients) > 0

            # Check if recipe has instructions
            instructions = recipe_data.get('recipeInstructions', [])
            has_instructions = len(instructions) > 0

            # Check if recipe has a meaningful name
            name = recipe_data.get('name', '').strip()
            has_name = len(name) > 3  # At least 4 characters

            if not has_name:
                return False, "Recipe has no valid name"
            elif not has_ingredients:
                return False, "Recipe has no ingredients"
            elif not has_instructions:
                return False, "Recipe has no instructions"
            else:
                return True, "Recipe is complete"

        except Exception as e:
            logger.error(f"Error validating recipe {recipe_slug}: {e}")
            return False, f"Error validating recipe: {str(e)}"

    async def get_recipe(self, recipe_id: str) -> Dict[str, Any]:
        """
        Get recipe details by ID

        Args:
            recipe_id: Mealie recipe ID

        Returns:
            Recipe data

        Raises:
            aiohttp.ClientError: If API request fails
            ValueError: If recipe not found
        """
        if not self.session:
            await self.connect()

        endpoint = f"{self.base_url}/api/recipes/{recipe_id}"

        try:
            async with self.session.get(endpoint) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    raise ValueError(f"Recipe {recipe_id} not found")
                else:
                    error_text = await response.text()
                    raise ValueError(f"Failed to get recipe: {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error while getting recipe: {e}")
            raise

    async def update_recipe(self, recipe_id: str, recipe_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing recipe

        Args:
            recipe_id: Mealie recipe ID
            recipe_data: Updated recipe data

        Returns:
            Updated recipe data

        Raises:
            aiohttp.ClientError: If API request fails
        """
        if not self.session:
            await self.connect()

        endpoint = f"{self.base_url}/api/recipes/{recipe_id}"

        try:
            async with self.session.put(endpoint, json=recipe_data) as response:
                if response.status == 200:
                    updated_data = await response.json()
                    logger.info(f"Successfully updated recipe: {recipe_id}")
                    return updated_data
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to update recipe. Status: {response.status}, Error: {error_text}")
                    raise ValueError(f"Failed to update recipe: {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error while updating recipe: {e}")
            raise

    def validate_recipe_data(self, recipe_data: Dict[str, Any]) -> tuple[bool, str]:
        """
        Validate if recipe has required components

        Args:
            recipe_data: Recipe data from Mealie

        Returns:
            Tuple of (is_valid, reason)
        """
        # Check if recipe has instructions
        if self.settings.require_instructions:
            instructions = recipe_data.get('recipeInstructions', [])
            if not instructions or all(not instr.strip() for instr in instructions):
                return False, "Recipe is missing instructions"

        # Check if recipe has ingredients
        if self.settings.require_ingredients:
            ingredients = recipe_data.get('recipeIngredient', [])
            if not ingredients or all(not ingr.strip() for ingr in ingredients):
                return False, "Recipe is missing ingredients"

        # Check if recipe has a title
        if not recipe_data.get('name', '').strip():
            return False, "Recipe is missing title"

        return True, "Recipe is valid"

    def get_recipe_url(self, recipe_slug: str) -> str:
        """
        Generate public URL for a recipe

        Args:
            recipe_slug: Recipe slug from Mealie

        Returns:
            Full URL to the recipe
        """
        # Use household format: /g/{household_slug}/r/{recipe_slug}
        return f"{self.base_url}/g/home/r/{recipe_slug}"

    async def _add_tags_to_recipe(self, recipe_slug: str, tags: List[str]):
        """
        Add tags to an existing recipe

        Args:
            recipe_slug: Recipe slug/ID
            tags: List of tags to add
        """
        if not self.session:
            await self.connect()

        # First get the current recipe data
        get_endpoint = f"{self.base_url}/api/recipes/{recipe_slug}"
        async with self.session.get(get_endpoint) as response:
            if response.status != 200:
                raise ValueError(f"Could not get recipe data: {response.status}")

            recipe_data = await response.json()

        # Strategy from old mealie-importer: create tags first, then assign them
        logger.info(f"Creating/ensuring tags exist: {tags}")

        # Step 1: Ensure all tags exist
        tag_objects = []
        for tag_name in tags:
            tag_obj = await self._ensure_tag_exists(tag_name)
            if tag_obj:
                tag_objects.append(tag_obj)
            else:
                logger.warning(f"Could not create/ensure tag: {tag_name}")

        if not tag_objects:
            logger.warning(f"No tags could be created/ensured for recipe {recipe_slug}")
            return

        # Step 2: Update recipe with tags
        logger.info(f"Assigning {len(tag_objects)} tags to recipe {recipe_slug}")

        # Add tags to existing tags - deduplicate by tag ID
        current_tags = recipe_data.get('tags', [])

        # Create a dict to deduplicate by tag ID
        all_tags_dict = {}

        # Add existing tags
        for tag in current_tags:
            if isinstance(tag, dict) and 'id' in tag:
                all_tags_dict[tag['id']] = tag

        # Add new tags (these will override if same ID exists)
        for tag in tag_objects:
            if tag and isinstance(tag, dict) and 'id' in tag:
                all_tags_dict[tag['id']] = tag

        # Convert back to list
        updated_tags = list(all_tags_dict.values())

        # Try with full tag objects first
        update_data_full = {
            'tags': updated_tags
        }

        # Also try with just tag IDs
        tag_ids = [tag['id'] for tag in updated_tags if 'id' in tag]
        update_data_ids = {
            'tags': tag_ids
        }

        # Try full objects first, then IDs if that fails
        update_data = update_data_full

        update_endpoint = f"{self.base_url}/api/recipes/{recipe_slug}"
        logger.info(f"Updating recipe {recipe_slug} with tag objects: {[tag['name'] for tag in tag_objects]}")

        async with self.session.patch(update_endpoint, json=update_data) as response:
            logger.info(f"Tag assignment response status: {response.status}")
            response_text = await response.text()
            logger.info(f"Response body: {response_text}")

            if response.status not in [200, 201, 204]:
                logger.error(f"Failed to assign tags to recipe: {response.status} - {response_text}")
                # Don't raise error - recipe was created successfully, just tags failed
                logger.warning(f"Recipe created but tags not assigned: {recipe_slug}")
            else:
                logger.info(f"Successfully assigned tags to recipe {recipe_slug}")

    async def _ensure_tag_exists(self, tag_name: str) -> Optional[Dict[str, Any]]:
        """Ensure a tag exists in Mealie, create if it doesn't exist"""
        if not self.session:
            await self.connect()

        # Generate slug for the tag
        tag_slug = self._generate_slug(tag_name)

        # Try to find existing tag first
        try:
            search_endpoint = f"{self.base_url}/api/organizers/tags"
            logger.info(f"Searching for existing tag: {tag_name}")

            async with self.session.get(search_endpoint, params={'perPage': -1}) as response:
                if response.status == 200:
                    search_data = await response.json()
                    tags_data = search_data.get('items', [])

                    # Find existing tag
                    existing_tag = None
                    for tag in tags_data:
                        if tag.get('name', '').lower() == tag_name.lower():
                            existing_tag = tag
                            break

                    if existing_tag:
                        logger.info(f"Tag '{tag_name}' already exists")
                        return existing_tag

        except Exception as search_error:
            logger.warning(f"Error searching for tag {tag_name}: {search_error}")

        # Tag doesn't exist, try to create it
        try:
            create_endpoint = f"{self.base_url}/api/organizers/tags"
            tag_data = {
                'name': tag_name,
                'slug': tag_slug
            }

            logger.info(f"Creating new tag: {tag_name}")
            async with self.session.post(create_endpoint, json=tag_data) as response:
                logger.info(f"Tag creation response status: {response.status}")
                response_text = await response.text()
                logger.info(f"Tag creation response: {response_text}")

                if response.status in [200, 201]:
                    # Try to parse the response as JSON
                    try:
                        created_tag = await response.json()
                        logger.info(f"Successfully created tag: {tag_name}")
                        return created_tag
                    except:
                        logger.info(f"Tag created but response not JSON: {response_text}")
                        # Return a mock object since we can't parse the response
                        return {'name': tag_name, 'slug': tag_slug}
                else:
                    logger.error(f"Failed to create tag {tag_name}: {response.status} - {response_text}")
                    return None

        except Exception as create_error:
            logger.error(f"Error creating tag {tag_name}: {create_error}")
            return None

    def _generate_slug(self, name: str) -> str:
        """Generate slug from name (similar to old mealie-importer)"""
        import re
        # Polish characters replacement
        name = name.lower()
        name = name.replace('ą', 'a').replace('ć', 'c').replace('ę', 'e')
        name = name.replace('ł', 'l').replace('ń', 'n').replace('ó', 'o')
        name = name.replace('ś', 's').replace('ź', 'z').replace('ż', 'z')
        # Replace non-alphanumeric characters with hyphens
        name = re.sub(r'[^a-z0-9]', '-', name)
        # Replace multiple hyphens with single hyphen
        name = re.sub(r'-+', '-', name)
        # Remove leading/trailing hyphens
        name = name.strip('-')
        return name

    async def parse_recipe_with_ai(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Parse recipe from URL using OpenAI

        Args:
            url: Recipe URL to parse

        Returns:
            Recipe data in Mealie format or None if failed
        """
        if not self.settings.openai_api_key:
            logger.warning("OpenAI API key not configured")
            return None

        try:
            # Fetch webpage content
            page_content = await self._fetch_webpage_content(url)
            if not page_content:
                logger.error(f"Could not fetch content from {url}")
                return None

            # Initialize OpenAI client
            client = AsyncOpenAI(api_key=self.settings.openai_api_key)

            # Create prompt for recipe extraction
            prompt = f"""
            Extract recipe information from the following webpage content.
            Return a JSON object with the following structure for Mealie:

            {{
                "name": "Recipe Title",
                "description": "Brief description of the recipe",
                "recipeIngredient": [
                    {{"note": "ingredient 1", "reference_id": "unique_id_1"}},
                    {{"note": "ingredient 2", "reference_id": "unique_id_2"}}
                ],
                "recipeInstructions": [
                    {{
                        "title": "Step 1",
                        "text": "Instruction text",
                        "id": "step_1_id"
                    }}
                ],
                "totalTime": "PT30M",  // ISO 8601 duration (optional)
                "recipeYield": "4",    // Number of servings (optional)
                "nutrition": {{         // Optional nutrition info
                    "calories": "300",
                    "proteinContent": "25g",
                    "fatContent": "15g",
                    "carbohydrateContent": "20g"
                }}
            }}

            IMPORTANT:
            - Extract ONLY the main recipe from the page
            - Include ALL ingredients with quantities
            - Include ALL cooking steps/instructions
            - Use clear, descriptive step titles
            - Generate unique reference_id for each ingredient
            - Generate unique id for each instruction step
            - If no nutrition info is available, omit the nutrition field
            - If no servings info, omit recipeYield
            - If no time info, omit totalTime

            Webpage content:
            {page_content[:8000]}  // Limit content length
            """

            # Call OpenAI API
            response = await client.chat.completions.create(
                model=self.settings.ai_model,
                messages=[
                    {"role": "system", "content": "You are a recipe extraction expert. Extract recipes from web pages and format them for cooking applications."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.1
            )

            # Parse JSON response
            import json
            recipe_json = response.choices[0].message.content.strip()

            # Clean up JSON (remove markdown code blocks if present)
            if recipe_json.startswith('```json'):
                recipe_json = recipe_json[7:]
            if recipe_json.endswith('```'):
                recipe_json = recipe_json[:-3]

            recipe_data = json.loads(recipe_json.strip())

            # Validate required fields
            if not recipe_data.get('name') or not recipe_data.get('recipeIngredient'):
                logger.error("AI response missing required fields")
                return None

            # Add default tags
            recipe_data['tags'] = self._get_default_tags()

            logger.info(f"Successfully parsed recipe with AI: {recipe_data['name']}")
            return recipe_data

        except Exception as e:
            logger.error(f"Error parsing recipe with AI: {e}")
            return None

    async def _fetch_webpage_content(self, url: str) -> Optional[str]:
        """
        Fetch webpage content for AI processing

        Args:
            url: URL to fetch

        Returns:
            Page content as string or None if failed
        """
        try:
            if not self.session:
                await self.connect()

            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()

                    # Get text content
                    text = soup.get_text(separator='\n', strip=True)

                    # Clean up whitespace
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    clean_text = '\n'.join(lines)

                    return clean_text
                else:
                    logger.error(f"Failed to fetch {url}: HTTP {response.status}")
                    return None

        except Exception as e:
            logger.error(f"Error fetching webpage {url}: {e}")
            return None

    async def create_recipe_from_ai_data(self, url: str, ai_recipe_data: Dict[str, Any]) -> Optional[str]:
        """
        Create recipe in Mealie using AI-parsed data

        Args:
            url: Original recipe URL
            ai_recipe_data: Recipe data from AI parsing

        Returns:
            Recipe slug if successful, None if failed
        """
        try:
            if not self.session:
                await self.connect()

            # Prepare recipe data for Mealie API
            recipe_payload = {
                'name': ai_recipe_data['name'],
                'description': ai_recipe_data.get('description', f'Recipe parsed by AI from {url}'),
                'recipeIngredient': ai_recipe_data.get('recipeIngredient', []),
                'recipeInstructions': ai_recipe_data.get('recipeInstructions', []),
            }

            # Add optional fields if available
            if 'totalTime' in ai_recipe_data:
                recipe_payload['totalTime'] = ai_recipe_data['totalTime']
            if 'recipeYield' in ai_recipe_data:
                recipe_payload['recipeYield'] = ai_recipe_data['recipeYield']
            if 'nutrition' in ai_recipe_data:
                recipe_payload['nutrition'] = ai_recipe_data['nutrition']

            # Add tags if available
            if 'tags' in ai_recipe_data:
                # Convert tag names to tag objects
                tag_objects = []
                for tag_name in ai_recipe_data['tags']:
                    tag_obj = await self._ensure_tag_exists(tag_name.strip())
                    if tag_obj:
                        tag_objects.append(tag_obj)
                if tag_objects:
                    recipe_payload['tags'] = tag_objects

            logger.info(f"Creating recipe from AI data: {recipe_payload['name']}")

            # Create recipe via Mealie API
            endpoint = f"{self.base_url}/api/recipes"
            async with self.session.post(endpoint, json=recipe_payload) as response:
                if response.status in [200, 201]:
                    response_data = await response.json()
                    recipe_slug = response_data.get('slug') or response_data.get('id')

                    if recipe_slug:
                        logger.info(f"Successfully created recipe from AI data: {recipe_slug}")
                        return recipe_slug
                    else:
                        logger.error("AI recipe creation succeeded but no slug returned")
                        return None
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create AI recipe: {response.status} - {error_text}")
                    return None

        except Exception as e:
            logger.error(f"Error creating recipe from AI data: {e}")
            return None
