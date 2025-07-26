#!/bin/bash
set -e

echo "🔧 Configuring SageAttention 2++..."

# Check if we need to build SageAttention from source for optimal performance
echo "🔍 Checking SageAttention installation..."
if ! python -c "import sageattention; print('✅ SageAttention imported successfully')" 2>/dev/null; then
    echo "📦 Installing SageAttention 2++ from source for optimal performance..."
    
    # Set build environment for optimal performance
    export TORCH_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0 12.0"
    export SAGEATTENTION_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}
    export MAX_JOBS=1
    export NVCC_THREADS=4
    
    # Clone and build SageAttention 2++
    cd /tmp
    git clone https://github.com/woct0rdho/SageAttention.git
    cd SageAttention
    python setup.py install
    cd /
    rm -rf /tmp/SageAttention
    
    echo "✅ SageAttention 2++ built and installed from source"
else
    echo "✅ SageAttention already installed"
fi

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
echo "🧪 Testing SageAttention 2++..."
python -c "
import sageattention
import torch

# Create test tensors in the correct format: [batch_size, num_heads, seq_len, head_dim]
batch_size, num_heads, seq_len, head_dim = 2, 8, 64, 64
q = torch.randn(batch_size, num_heads, seq_len, head_dim, dtype=torch.float16).cuda()
k = torch.randn(batch_size, num_heads, seq_len, head_dim, dtype=torch.float16).cuda()
v = torch.randn(batch_size, num_heads, seq_len, head_dim, dtype=torch.float16).cuda()

# Test sageattn function with SageAttention 2++ features
try:
    output = sageattention.sageattn(q, k, v, tensor_layout='HND')
    print('✅ SageAttention 2++ test passed')
    
    # Test additional SageAttention 2++ features if available
    try:
        # Test with different tensor layouts
        output_ndh = sageattention.sageattn(q, k, v, tensor_layout='NDH')
        print('✅ SageAttention 2++ NDH layout test passed')
    except:
        print('ℹ️  NDH layout not available in this version')
        
except Exception as e:
    print(f'❌ SageAttention test failed: {e}')
    exit(1)
" || {
    echo "❌ SageAttention functionality test failed"
    exit 1
}

echo "✅ SageAttention 2++ configuration complete"