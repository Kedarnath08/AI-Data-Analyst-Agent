Step 1: Clone the Repo and Navigate to RAG-Chatbot-Backend. Later create a virtual environment using below command and activate the virtual environment

   1.git clone URL
  
   2.python -m venv virtual_environment_name
  
   3.virtual_environment_name\Scripts\Activate.ps1 (powershell)

Step 2: Install all the libraries of python using below command
  pip install -r requirements.txt

Step 3: Run the below command so that the uvicorn is up and swagger page appears to interact with API's
  uvicorn api:apps --host 0.0.0.0 --port 8090

Step 4 (optional): Run the test suite. Tests mock the Gemini/embedding/vector-search calls, but the app still needs a valid PINECONE_API_KEY in .env to import (it connects to your real Pinecone project at startup).
  pip install -r requirements-dev.txt
  pytest

