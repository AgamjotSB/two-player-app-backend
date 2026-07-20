import httpx
from fastapi import HTTPException, status

from app.config import Config
from app.models.sudoku import SudokuDifficulty

http_client: httpx.AsyncClient | None = None


async def fetch_sudoku_puzzle(difficulty: SudokuDifficulty) -> tuple[str, str]:
    assert http_client is not None, "http_client not initialized, check lifespan setup"

    try:
        response = await http_client.post(
            Config.youdosudoku_endpoint,
            json={"difficulty": difficulty.value, "solution": True, "array": False},
            headers={
                "Content-Type": "application/json",
                "x-api-key": Config.youdosudoku_api_key,
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch a puzzle right now, try again",
        ) from e

    data = response.json()
    return data["puzzle"], data["solution"]
