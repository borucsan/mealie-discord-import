"""Tests for Mealie API client"""

import pytest
from unittest.mock import AsyncMock, MagicMock
import aiohttp

from config.settings import Settings
from mealie.client import MealieClient
from mealie.models import RecipeData


class TestMealieClient:
    """Test cases for MealieClient"""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing"""
        settings = MagicMock(spec=Settings)
        settings.mealie_base_url = "https://test-mealie.com"
        settings.mealie_api_token = "test-token"
        settings.default_recipe_tags = ["Discord Import", "Verify"]
        settings.require_instructions = True
        settings.require_ingredients = True
        return settings

    @pytest.fixture
    def client(self, mock_settings):
        """MealieClient instance for testing"""
        return MealieClient(mock_settings)

    def test_init(self, client, mock_settings):
        """Test client initialization"""
        assert client.settings == mock_settings
        assert client.base_url == mock_settings.mealie_base_url
        assert client.api_token == mock_settings.mealie_api_token
        assert client.session is None

    def test_validate_recipe_data_valid(self, client):
        """Test recipe validation with valid data"""
        valid_recipe = {
            'name': 'Test Recipe',
            'recipeInstructions': ['Step 1', 'Step 2'],
            'recipeIngredient': ['Ingredient 1', 'Ingredient 2']
        }

        is_valid, reason = client.validate_recipe_data(valid_recipe)
        assert is_valid is True
        assert reason == "Recipe is valid"

    def test_validate_recipe_data_missing_instructions(self, client):
        """Test recipe validation with missing instructions"""
        invalid_recipe = {
            'name': 'Test Recipe',
            'recipeInstructions': [],
            'recipeIngredient': ['Ingredient 1', 'Ingredient 2']
        }

        is_valid, reason = client.validate_recipe_data(invalid_recipe)
        assert is_valid is False
        assert "missing instructions" in reason

    def test_validate_recipe_data_missing_ingredients(self, client):
        """Test recipe validation with missing ingredients"""
        invalid_recipe = {
            'name': 'Test Recipe',
            'recipeInstructions': ['Step 1', 'Step 2'],
            'recipeIngredient': []
        }

        is_valid, reason = client.validate_recipe_data(invalid_recipe)
        assert is_valid is False
        assert "missing ingredients" in reason

    def test_validate_recipe_data_missing_title(self, client):
        """Test recipe validation with missing title"""
        invalid_recipe = {
            'name': '',
            'recipeInstructions': ['Step 1', 'Step 2'],
            'recipeIngredient': ['Ingredient 1', 'Ingredient 2']
        }

        is_valid, reason = client.validate_recipe_data(invalid_recipe)
        assert is_valid is False
        assert "missing title" in reason

    def test_get_recipe_url(self, client):
        """Test recipe URL generation"""
        slug = "test-recipe-slug"
        expected_url = "https://test-mealie.com/recipe/test-recipe-slug"

        result = client.get_recipe_url(slug)
        assert result == expected_url

    @pytest.mark.asyncio
    async def test_create_recipe_from_url_success(self, client):
        """Test successful recipe creation from URL"""
        # Mock response
        mock_response = AsyncMock()
        mock_response.status = 201
        mock_response.json = AsyncMock(return_value={
            'id': '123',
            'name': 'Test Recipe',
            'slug': 'test-recipe'
        })

        # Mock session with proper context manager
        mock_session = AsyncMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)

        client.session = mock_session

        result = await client.create_recipe_from_url("https://example.com/recipe")

        assert result['id'] == '123'
        assert result['name'] == 'Test Recipe'
        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_recipe_from_url_failure(self, client):
        """Test failed recipe creation from URL"""
        # Mock response
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        # Mock session with proper context manager
        mock_session = AsyncMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)

        client.session = mock_session

        with pytest.raises(ValueError, match="Failed to create recipe"):
            await client.create_recipe_from_url("https://example.com/recipe")
