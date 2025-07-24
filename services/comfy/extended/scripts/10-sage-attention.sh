#!/bin/bash
set -e

echo "🔧 Configuring SageAttention..."

# Verify SageAttention installation
python -c "import sageattention; print('✅ SageAttention imported successfully')" || {
    echo "❌ SageAttention not properly installed"
    exit 1
}

# Verify CUDA availability
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')" || {
    echo "⚠️  CUDA not available, SageAttention will use CPU fallback"
}

# Test basic SageAttention functionality
echo "🧪 Testing SageAttention..."
python -c "
import sageattention
import torch

# Create test tensors in the correct format: [batch_size, num_heads, seq_len, head_dim]
batch_size, num_heads, seq_len, head_dim = 2, 8, 64, 64
q = torch.randn(batch_size, num_heads, seq_len, head_dim, dtype=torch.float16).cuda()
k = torch.randn(batch_size, num_heads, seq_len, head_dim, dtype=torch.float16).cuda()
v = torch.randn(batch_size, num_heads, seq_len, head_dim, dtype=torch.float16).cuda()

# Test sageattn function
try:
    output = sageattention.sageattn(q, k, v, tensor_layout='HND')
    print('✅ SageAttention test passed')
except Exception as e:
    print(f'❌ SageAttention test failed: {e}')
    exit(1)
" || {
    echo "❌ SageAttention functionality test failed"
    exit 1
}

echo "✅ SageAttention configuration complete"