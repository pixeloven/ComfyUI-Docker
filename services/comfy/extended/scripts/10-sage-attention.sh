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

# Create test tensors
batch_size, seq_len, hidden_dim = 2, 64, 128
q = torch.randn(batch_size, seq_len, hidden_dim).cuda()
k = torch.randn(batch_size, seq_len, hidden_dim).cuda()
v = torch.randn(batch_size, seq_len, hidden_dim).cuda()

# Test forward pass
try:
    output = sageattention.forward(q, k, v)
    print('✅ SageAttention test passed')
except Exception as e:
    print(f'❌ SageAttention test failed: {e}')
    exit(1)
" || {
    echo "❌ SageAttention functionality test failed"
    exit 1
}

echo "✅ SageAttention configuration complete"