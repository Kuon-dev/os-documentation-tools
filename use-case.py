import os
from dotenv import load_dotenv
from typing import List, Tuple
import re
import argparse 
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress
from rich.markdown import Markdown

load_dotenv()

# Constants
PROJECT_ROOT = 'C:/Users/aaron/OneDrive - Asia Pacific University/deg sem 3/FYP/project/fyp-back'
OUTPUT_DIR = './output'
RELEVANT_FILE_EXTENSIONS = ('.ts', '.js', '.prisma')
ANTHROPIC_MODEL = "claude-3-sonnet-20240229"
PRICE_PER_1K_TOKENS = 0.002  # Adjust this based on the current pricing

# Initialize Rich console
console = Console()

# Regular expressions
CONTROLLER_METHOD_REGEX = r'async\s+(\w+)\s*\([^)]*\)\s*{'
PRISMA_MODEL_REGEX = r'model\s+(\w+)\s*{'

# Prompt template
USE_CASE_TEMPLATE = """
Based on the following analysis of a controller component, generate detailed use case specifications for the operations identified:

{analysis}

For each operation identified in the analysis, create a comprehensive use case specification using the following structure:

# Use Case Specifications

## [Operation Name]
| Section | Description |
|---------|-------------|
| Use Case Name | [Clear, action-oriented name for the operation] |
| Description | [Brief description of the operation, its purpose, and context] |
| Actors | Primary Actor: End User<br>Secondary Actor(s): System |
| Preconditions | [Conditions that must be true before the operation can be performed] |
| Postconditions | [System state after the operation has been successfully completed] |
| Standard Process | [Numbered steps describing the main success scenario] |
| Alternative Processes | [Alternative paths, numbered as subsets of the main process steps, e.g., 2a for an alternative to step 2] |
| Exception Processes | [Error handling processes such as validation errors, numbered as subsets of the main process steps, e.g., 3a for an exception in step 3] |

Important guidelines:
1. Always set the primary actor as "End User" and the secondary actor as "System" for all operations.
2. For CRUD operations (create, getById, update, delete), follow common patterns but adapt to the specific implementation in the controller.
3. Pay special attention to operations like search, getPaginated, and getFeatured, which may have unique parameters and behaviors.
4. Consider authentication and authorization requirements, especially for operations that check for a logged-in user.
5. Include details about input validation, especially when Zod schemas are used for request body parsing.
6. For operations that interact with services (e.g., RepoService, CodeCheckService), describe the general purpose without diving into implementation details.
7. When describing processes involving database operations, use generic terms like "database" instead of specific technologies.
8. For search operations, detail the various search criteria and how they affect the results.
9. For operations returning paginated results, include information about pagination in the process and postconditions.
10. Write all components considering the interaction between the end user and the system, focusing on what the user does and how the system responds.
11. If there are similar operations across multiple controllers (e.g GetAll and GetById), combine them into a single use case specification with clear distinctions between the controllers.

Common considerations for different types of operations:
- CRUD Operations:
  - Create: Data validation, handling of user-provided data, status setting (e.g., 'pending')
  - Read: Retrieving associated data (e.g., CodeCheck results), handling public vs. private access
  - Update: Partial updates, handling of sensitive fields, potential code checking processes
  - Delete: Ensuring user authorization, handling of associated data
- Search Operations: Handling of multiple search criteria, pagination, potential security considerations for visibility
- List Operations (e.g., getPaginated, getByUser): Pagination, filtering, handling of user-specific data
- Featured Content: Criteria for featuring, limit handling

Remember to adapt the content of each operation based on the provided analysis, considering the controller methods and their specific implementations, while maintaining the end user as the primary actor initiating the actions. Generate a separate use case specification for each distinct operation identified in the analysis.
"""

def initialize_llm():
    """Initialize and return the Anthropic LLM."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
    return ChatAnthropic(
        model=ANTHROPIC_MODEL,
        temperature=0,
        max_tokens=4096,
        timeout=None,
        max_retries=2,
    )

def analyze_file(file_path: str) -> str:
    """Analyze the content of a file."""
    with open(file_path, 'r') as file:
        content = file.read()
    
    file_name = os.path.basename(file_path)
    
    if 'Controller' in file_name:
        methods = re.findall(CONTROLLER_METHOD_REGEX, content)
        operations = []
        for method in methods:
            if method.startswith(('create', 'get', 'update', 'delete')):
                operations.append(f"CRUD Operation: {method}")
            else:
                operations.append(f"Specific Operation: {method}")
        return f"Controller: {file_name}\nOperations: {', '.join(operations)}"
    elif file_name == 'schema.prisma':
        models = re.findall(PRISMA_MODEL_REGEX, content)
        return f"Prisma Schema Models: {', '.join(models)}"
    else:
        return f"Unknown file type: {file_name}\nContent preview: {content[:200]}..."

def generate_use_case(llm: ChatAnthropic, analysis: str) -> Tuple[str, int]:
    """Generate a use case specification using LangChain and Anthropic."""
    with Progress() as progress:
        task = progress.add_task("[cyan]Generating use case specification...", total=100)
        
        prompt = ChatPromptTemplate.from_template(USE_CASE_TEMPLATE)
        chain = prompt | llm | StrOutputParser()
        
        progress.update(task, advance=50)
        result = chain.invoke({"analysis": analysis})
        
        # Get total token usage
        total_tokens = llm.get_num_tokens(USE_CASE_TEMPLATE.format(analysis=analysis) + result)
        
        progress.update(task, advance=50)
    
    return result, total_tokens

def save_use_case(file_path: str, use_case: str, token_usage: int):
    """Save the generated use case specification to a file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    base_name = os.path.basename(file_path)
    use_case_file_name = f"use_case_{os.path.splitext(base_name)[0]}.md"
    output_path = os.path.join(OUTPUT_DIR, use_case_file_name)
    
    estimated_cost = (token_usage / 1000) * PRICE_PER_1K_TOKENS
    
    with open(output_path, 'w') as f:
        f.write(use_case)
        f.write(f"\n\n---\n\n")
        f.write(f"Token usage: {token_usage}\n")
        f.write(f"Estimated cost: ${estimated_cost:.4f}")
    
    console.print(Panel.fit(f"[green]Generated use case specifications: {output_path}[/green]"))
    
    # Display a preview of the markdown content in the console
    preview = use_case[:1000] + "..." if len(use_case) > 1000 else use_case
    md = Markdown(preview)
    console.print(md)
    
    # Display token usage and cost
    usage_table = Table(title="Usage Statistics")
    usage_table.add_column("Metric", style="cyan")
    usage_table.add_column("Value", style="magenta")
    usage_table.add_row("Token Usage", str(token_usage))
    usage_table.add_row("Estimated Cost", f"${estimated_cost:.4f}")
    console.print(usage_table)

def main():
    parser = argparse.ArgumentParser(description="Generate a use case specification for a single file.")
    parser.add_argument("file_path", help="Path to the file to analyze")
    args = parser.parse_args()

    console.print(Panel.fit("[bold blue]Kortex Use Case Specification Generator[/bold blue]"))

    llm = initialize_llm()
    analysis = analyze_file(args.file_path)
    
    console.print(f"[yellow]Analyzing:[/yellow] {args.file_path}")
    console.print(Panel(analysis, title="Analysis Result", expand=False))
    
    use_case, token_usage = generate_use_case(llm, analysis)
    save_use_case(args.file_path, use_case, token_usage)

if __name__ == "__main__":
    main()
