import os
import sys
from typing import List, Dict, Any, Tuple
from langchain_core.prompts import ChatPromptTemplate
# from langchain_anthropic import ChatAnthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
import logging
from dotenv import load_dotenv
from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

# Load environment variables
load_dotenv()

# Set up rich logging
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
log = logging.getLogger("rich")
console = Console()

# Constants for pricing
PRICE_PER_1M_INPUT_TOKENS = 0.25  # $3 per 1M input tokens
PRICE_PER_1M_OUTPUT_TOKENS = 1.25  # $15 per 1M output tokens

def get_gitignore_spec(directory: str) -> PathSpec:
    gitignore_path = os.path.join(directory, '.gitignore')
    if os.path.exists(gitignore_path):
        with open(gitignore_path, 'r') as gitignore_file:
            gitignore_content = gitignore_file.read()
        return PathSpec.from_lines(GitWildMatchPattern, gitignore_content.splitlines())
    return PathSpec([])

def read_project_files(directory: str) -> Tuple[str, str, List[str]]:
    gitignore_spec = get_gitignore_spec(directory)
    typescript_content = ""
    prisma_schema = ""
    file_list = []
    
    for root, dirs, files in os.walk(directory):
        # Skip .git and other unnecessary directories
        dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', 'dist', 'build']]
        
        rel_path = os.path.relpath(root, directory)
        
        if "tests" in rel_path.split(os.path.sep) or "seeders" in rel_path.split(os.path.sep) or "config" in rel_path.split(os.path.sep):
            continue
        
        if gitignore_spec.match_file(rel_path):
            continue
        
        for file in files:
            if file.endswith('.ts') or file == 'schema.prisma':
                file_path = os.path.join(root, file)
                rel_file_path = os.path.relpath(file_path, directory)
                if not gitignore_spec.match_file(rel_file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            if file.endswith('.ts'):
                                typescript_content += f"\n\n--- {rel_file_path} ---\n\n{content}"
                            elif file == 'schema.prisma':
                                prisma_schema = content
                            file_list.append(rel_file_path)
                    except Exception as e:
                        log.error(f"[red]Error reading file {file_path}: {str(e)}[/red]")
    
    log.info(f"[green]Read {len(file_list)} files (including Prisma schema)[/green]")
    return typescript_content, prisma_schema, file_list

def generate_diagram(typescript_content: str, prisma_schema: str) -> Tuple[str, int, int]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("[red]ANTHROPIC_API_KEY not found in environment variables[/red]")
        return "", 0, 0
    
    llm = ChatAnthropic(model="claude-3-haiku-20240307", anthropic_api_key=api_key, max_tokens=4096)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert in software architecture and database modeling. Your task is to analyze TypeScript code and a Prisma schema to generate a class diagram that focuses primarily on relationships between entities."),
        ("human", """
        Analyze the following TypeScript code and Prisma schema, then generate a class diagram focusing on relationships:

        TypeScript Code:
        {typescript_content}

        Prisma Schema:
        {prisma_schema}

        Follow these strict guidelines:
        1. Identify all entities (classes, interfaces, and models) from both the TypeScript code and Prisma schema.
        2. For each entity, include ONLY the name. DO NOT include attributes or methods unless they are crucial for understanding a relationship.
        3. Focus EXCLUSIVELY on representing relationships between entities:
           - One-to-One: Use --> with "1" on both ends
           - One-to-Many: Use --> with "1" on one end and "*" on the other
           - Many-to-Many: Use --> with "*" on both ends
           - Inheritance: Use <|--
           - Implementation: Use <|..
        4. Use "classDiagram" to start the Mermaid class diagram.
        5. Represent entities with the syntax: class EntityName
        6. Represent relationships with the correct arrows and cardinality, e.g.:
           EntityA "1" --> "*" EntityB : has many
        7. Include enum types ONLY if they are directly involved in a relationship. Otherwise, omit them.
        8. Organize the diagram for maximum readability, grouping related entities together.
        9. If there are many entities, focus on the most important ones and their relationships.
        10. DO NOT include any attributes in the diagram unless they are absolutely crucial for understanding a relationship.

        Output ONLY the Mermaid code for the diagram, without any additional explanation or markdown formatting. The diagram should ONLY show relationships between entities, not their internal structure.
        """)
    ])
    
    chain = prompt | llm | StrOutputParser()
    
    try:
        diagram = chain.invoke({"typescript_content": typescript_content, "prisma_schema": prisma_schema})
        log.info("[green]Diagram generated successfully[/green]")
        
        # Calculate token usage
        input_tokens = llm.get_num_tokens(prompt.format(typescript_content=typescript_content, prisma_schema=prisma_schema))
        output_tokens = llm.get_num_tokens(diagram)
        
        return diagram, input_tokens, output_tokens
    except Exception as e:
        log.error(f"[red]Error generating diagram: {str(e)}[/red]")
        return "", 0, 0

def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1_000_000) * PRICE_PER_1M_INPUT_TOKENS
    output_cost = (output_tokens / 1_000_000) * PRICE_PER_1M_OUTPUT_TOKENS
    total_cost = input_cost + output_cost
    return total_cost

def save_diagram_to_file(diagram: str, file_path: str):
    try:
        with open(file_path, 'w') as f:
            f.write("```mermaid\n")
            f.write(diagram)
            f.write("\n```")
        log.info(f"[green]Diagram saved to {file_path}[/green]")
    except Exception as e:
        log.error(f"[red]Error saving diagram to file: {str(e)}[/red]")

def generate_class_diagram(directory: str) -> Tuple[str, int, int, float, List[str]]:
    try:
        typescript_content, prisma_schema, file_list = read_project_files(directory)
        
        if not typescript_content and not prisma_schema:
            log.error(f"[red]No TypeScript files or Prisma schema found in directory: {directory}[/red]")
            return "", 0, 0, 0.0, []
        
        diagram, input_tokens, output_tokens = generate_diagram(typescript_content, prisma_schema)
        cost = calculate_cost(input_tokens, output_tokens)
        
        return diagram, input_tokens, output_tokens, cost, file_list
    except Exception as e:
        log.error(f"[red]Error in main pipeline: {str(e)}[/red]")
        return "", 0, 0, 0.0, []

def display_file_list(file_list: List[str]):
    table = Table(title="Processed TypeScript Files")
    table.add_column("File Path", style="cyan")
    for file_path in file_list:
        table.add_row(file_path)
    console.print(table)

if __name__ == "__main__":
    console.print("[bold green]Class Diagram Generator for TypeScript and Prisma[/bold green]")
    
    project_directory = os.getenv("PROJECT_DIRECTORY")
    if not project_directory:
        console.print("[bold red]PROJECT_DIRECTORY not found in environment variables[/bold red]")
        console.print("Please set the PROJECT_DIRECTORY in your .env file")
        sys.exit(1)
    
    console.print(f"[cyan]Analyzing project directory: {project_directory}[/cyan]")
    
    class_diagram, input_tokens, output_tokens, cost, file_list = generate_class_diagram(project_directory)
    if class_diagram:
        console.print("[bold green]Class diagram generated successfully![/bold green]")
        console.print(class_diagram)
        save_diagram_to_file(class_diagram, "combined_class_diagram.md")
        
        # Display the list of processed files
        display_file_list(file_list)
        
        # Display token usage and cost
        table = Table(title="Token Usage and Cost")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")
        table.add_row("Input Tokens", str(input_tokens))
        table.add_row("Output Tokens", str(output_tokens))
        table.add_row("Total Tokens", str(input_tokens + output_tokens))
        table.add_row("Estimated Cost", f"${cost:.4f}")
        console.print(table)
    else:
        console.print("[bold red]Failed to generate class diagram. Check logs for details.[/bold red]")
