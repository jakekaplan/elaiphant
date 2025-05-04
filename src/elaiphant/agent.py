from pydantic import BaseModel, Field
from pydantic_ai import Agent

from elaiphant.settings import settings


class QueryAnalysisInput(BaseModel):
    """Input model for the query analysis agent."""

    sql_query: str = Field(..., description="The SQL query to analyze.")
    explain_analyze_output: str = Field(
        ..., description="The output of EXPLAIN ANALYZE for the query."
    )


class OptimizationSuggestion(BaseModel):
    """Represents a single optimization suggestion."""

    suggestion_type: str = Field(
        ..., description="Type of suggestion (e.g., 'index', 'rewrite', 'config')."
    )
    description: str = Field(..., description="Detailed description of the suggestion.")


class QueryAnalysisOutput(BaseModel):
    """Output model for the query analysis agent."""

    suggestions: list[OptimizationSuggestion] = Field(
        default_factory=list, description="List of optimization suggestions."
    )


def create_optimizer_agent() -> Agent[None, QueryAnalysisOutput]:
    """Creates a pydantic-ai agent configured for query optimization using settings.

    Returns:
        A configured pydantic_ai.Agent instance.

    Uses:
        settings.ai_model: The LLM model string (e.g., 'openai:gpt-4o') from settings.
        Environment variables (e.g., OPENAI_API_KEY) for authentication, handled by pydantic-ai.
    """
    system_prompt = """
Analyze the provided PostgreSQL query and its EXPLAIN ANALYZE output.
Your goal is to suggest optimizations to improve performance.
Focus on actionable advice like:
- Index recommendations (CREATE INDEX ...)
- Query rewrites (alternative SQL formulations)
- Relevant PostgreSQL configuration changes

Return your suggestions using the available structured output format.
If no suggestions are applicable, return an empty list of suggestions.
"""

    # Create the agent, passing the model string from settings
    agent: Agent[None, QueryAnalysisOutput] = Agent(
        settings.ai_model,  # Use model string from settings
        output_type=QueryAnalysisOutput,
        system_prompt=system_prompt,
        # tools=[], # Explicitly empty tools list
        # instrument=True, # Consider enabling for Logfire integration later
    )
    return agent


async def analyze_query_with_agent(
    agent: Agent[None, QueryAnalysisOutput], analysis_input: QueryAnalysisInput
) -> QueryAnalysisOutput:
    """Runs the optimizer agent with the given query input.

    Args:
        agent: The configured pydantic_ai.Agent instance.
        analysis_input: The input containing the SQL query and EXPLAIN output.

    Returns:
        The QueryAnalysisOutput containing optimization suggestions.
    """
    # Construct the user message part of the prompt
    user_prompt = f"""
SQL Query:
```sql
{analysis_input.sql_query}
```

EXPLAIN ANALYZE Output:
```
{analysis_input.explain_analyze_output}
```

Please provide optimization suggestions.
"""

    # Run the agent
    # pydantic-ai handles calling the LLM, structuring the prompt,
    # and validating the output against QueryAnalysisOutput.
    result = await agent.run(user_prompt)

    return result.output
