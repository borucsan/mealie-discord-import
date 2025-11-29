"""Data models for Mealie recipes"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class RecipeIngredient(BaseModel):
    """Recipe ingredient model"""
    title: str
    note: Optional[str] = None


class RecipeInstruction(BaseModel):
    """Recipe instruction model"""
    text: str
    title: Optional[str] = None


class RecipeNutrition(BaseModel):
    """Recipe nutrition information"""
    calories: Optional[str] = None
    fat_content: Optional[str] = None
    protein_content: Optional[str] = None
    carbohydrate_content: Optional[str] = None


class RecipeData(BaseModel):
    """Complete recipe data model"""
    name: str = Field(..., description="Recipe title")
    description: Optional[str] = None
    recipe_ingredient: List[str] = Field(default_factory=list, description="List of ingredients")
    recipe_instructions: List[str] = Field(default_factory=list, description="List of instructions")
    recipe_yield: Optional[str] = None
    total_time: Optional[str] = None
    prep_time: Optional[str] = None
    cook_time: Optional[str] = None
    tags: List[str] = Field(default_factory=list, description="Recipe tags")
    recipe_category: List[str] = Field(default_factory=list, description="Recipe categories")
    nutrition: Optional[RecipeNutrition] = None
    image: Optional[str] = None
    slug: Optional[str] = None
    id: Optional[str] = None

    class Config:
        allow_population_by_field_name = True


class CreateRecipeRequest(BaseModel):
    """Request model for creating recipes from URLs"""
    url: str
    tags: List[str] = Field(default_factory=list)


class RecipeResponse(BaseModel):
    """Response model from Mealie API"""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    recipe_ingredient: List[str] = Field(default_factory=list)
    recipe_instructions: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    image: Optional[str] = None


class RecipeValidationResult(BaseModel):
    """Result of recipe validation"""
    is_valid: bool
    reason: str
    missing_components: List[str] = Field(default_factory=list)
