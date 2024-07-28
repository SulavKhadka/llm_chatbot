from typing import List, Union
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel

folder_path = "~/Repos/rag-experiments/research/data/TF_ID_images/big_load"
def rag_dataloader(file_paths: List[str]):
    pass





class NomicTextEmbedder:
    def __init__(self):
        self.model_name = 'nomic-ai/nomic-embed-text-v1.5'
        self.tokenizer = AutoTokenizer.from_pretrained('bert-base-uncased')
        self.model = AutoModel.from_pretrained(self.model_name, trust_remote_code=True, safe_serialization=True)
        self.model.eval()

    def tokenize(self, texts: Union[str, List[str]]) -> List[List[int]]:
        """
        Tokenize the input text(s).
        
        Args:
            texts (Union[str, List[str]]): Input text or list of texts to tokenize.
        
        Returns:
            List[List[int]]: List of token IDs for each input text.
        """
        if isinstance(texts, str):
            texts = [texts]
        
        encoded_input = self.tokenizer(texts)
        return encoded_input.get('input_ids', [])

    @torch.no_grad()
    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        Generate embeddings for the input text(s).
        
        Args:
            texts (Union[str, List[str]]): Input text or list of texts to embed.
        
        Returns:
            List[List[float]]: List of embeddings for each input text.
        """
        if isinstance(texts, str):
            texts = [texts]
        
        encoded_input = self.tokenizer(texts, padding=True, truncation=True, return_tensors='pt')
        
        model_output = self.model(**encoded_input)
        
        token_embeddings = model_output[0]
        input_mask_expanded = encoded_input['attention_mask'].unsqueeze(-1).expand(token_embeddings.size()).float()
        embeddings = torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        embeddings = F.normalize(embeddings, p=2, dim=1)
        
        return embeddings.tolist()

    def __call__(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        Allow the class to be called directly to generate embeddings.
        
        Args:
            texts (Union[str, List[str]]): Input text or list of texts to embed.
        
        Returns:
            List[List[float]]: List of embeddings for each input text.
        """
        return self.embed(texts)