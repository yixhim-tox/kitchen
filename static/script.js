// Flame background effect
window.addEventListener('DOMContentLoaded', function () {
  const flame = document.createElement('div');
  flame.style.position = 'fixed';
  flame.style.top = '0';
  flame.style.left = '0';
  flame.style.width = '100%';
  flame.style.height = '100%';
  flame.style.backgroundImage = "url('https://i.ibb.co/3fvHZhh/fire.gif')";
  flame.style.backgroundSize = 'cover';
  flame.style.backgroundRepeat = 'no-repeat';
  flame.style.backgroundPosition = 'center';
  flame.style.opacity = '0.05';
  flame.style.zIndex = '-1';
  document.body.appendChild(flame);
});

// Initialize cart
let cart = JSON.parse(localStorage.getItem('cart')) || [];

function addToCart(name, price) {
  let found = false;

  for (let i = 0; i < cart.length; i++) {
    if (cart[i].name === name) {
      cart[i].quantity += 1;
      found = true;
      break;
    }
  }

  if (!found) {
    cart.push({ name: name, price: price, quantity: 1 });
  }

  localStorage.setItem('cart', JSON.stringify(cart));
  alert(name + " added to cart!");
}

function loadCart() {
  let cartItems = document.getElementById('cart-items');
  let totalPrice = document.getElementById('total-price');

  if (!cartItems || !totalPrice) return;

  cartItems.innerHTML = '';
  let total = 0;

  cart.forEach(function (item, index) {
    let itemTotal = item.price * item.quantity;
    total += itemTotal;

    let row = `
      <tr>
        <td>${item.name}</td>
        <td>₦${item.price.toFixed(2)}</td>
        <td>
          <button onclick="changeQty(${index}, -1)">-</button>
          ${item.quantity}
          <button onclick="changeQty(${index}, 1)">+</button>
        </td>
        <td>₦${itemTotal.toFixed(2)}</td>
        <td><button onclick="removeItem(${index})">Remove</button></td>
      </tr>
    `;

    cartItems.innerHTML += row;
  });

  totalPrice.textContent = '₦' + total.toFixed(2);
}

function changeQty(index, amount) {
  if (cart[index]) {
    cart[index].quantity += amount;

    if (cart[index].quantity <= 0) {
      cart.splice(index, 1);
    }

    localStorage.setItem('cart', JSON.stringify(cart));
    loadCart();
  }
}

function removeItem(index) {
  cart.splice(index, 1);
  localStorage.setItem('cart', JSON.stringify(cart));
  loadCart();
}

function checkoutCart() {
  if (cart.length === 0) {
    alert('Your cart is empty.');
    return;
  }

  alert('Checkout successful!');
  cart = [];
  localStorage.removeItem('cart');
  loadCart();
}
