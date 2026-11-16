(function(){
  const form=document.getElementById('student-feedback-form');
  if(!form)return;
  const list=document.getElementById('dish-list');
  const search=document.getElementById('dish-search');
  const count=document.getElementById('selected-dish-count');
  const panel=document.getElementById('dish-panel');
  const submit=document.getElementById('submit-feedback');
  const catalog=JSON.parse(document.getElementById('menu-catalog').textContent||'[]');
  const lang=document.documentElement.lang==='he'?'he':'en';
  const words={
    en:{rate:'Rate this dish',none:'No dishes selected — you can still send your feedback.',one:'1 dish selected.',many:n=>n+' dishes selected.',missing:'Please rate each dish you selected.'},
    he:{rate:'דרגו את המנה',none:'לא נבחרו מנות — אפשר לשלוח משוב גם כך.',one:'נבחרה מנה אחת.',many:n=>'נבחרו '+n+' מנות.',missing:'יש לדרג כל מנה שבחרתם.'}
  };
  function updateCount(){
    const selected=list.querySelectorAll('input[name="dish_slug"]:checked').length;
    count.textContent=selected===0?words[lang].none:selected===1?words[lang].one:words[lang].many(selected);
  }
  function renderDish(item){
    const card=document.createElement('article');
    card.className='dish-item';
    const label=document.createElement('label');
    label.className='dish-item-choice';
    const checkbox=document.createElement('input');
    checkbox.type='checkbox';
    checkbox.name='dish_slug';
    checkbox.value=item[0];
    const title=document.createElement('span');
    title.textContent=lang==='he'?item[1]:item[2];
    label.append(checkbox,title);
    card.append(label);
    const ratings=document.createElement('fieldset');
    ratings.className='dish-item-rating';
    ratings.disabled=true;
    const legend=document.createElement('legend');
    legend.textContent=words[lang].rate;
    ratings.append(legend);
    const row=document.createElement('div');
    row.className='dish-stars';
    for(let value=1;value<=5;value++){
      const ratingLabel=document.createElement('label');
      const radio=document.createElement('input');
      radio.type='radio';
      radio.name='dish_rating_'+item[0];
      radio.value=String(value);
      radio.required=true;
      const star=document.createElement('span');
      star.textContent='★';
      star.setAttribute('aria-hidden','true');
      const number=document.createElement('small');
      number.textContent=String(value);
      ratingLabel.append(radio,star,number);
      row.append(ratingLabel);
    }
    ratings.append(row);
    card.append(ratings);
    checkbox.addEventListener('change',()=>{
      ratings.disabled=!checkbox.checked;
      ratings.querySelectorAll('input').forEach(radio=>{
        radio.required=checkbox.checked;
        if(!checkbox.checked)radio.checked=false;
      });
      card.classList.toggle('is-selected',checkbox.checked);
      updateCount();
    });
    return card;
  }
  catalog.forEach(item=>list.append(renderDish(item)));
  updateCount();
  search.addEventListener('input',()=>{
    const query=search.value.trim().toLocaleLowerCase();
    list.querySelectorAll('.dish-item').forEach(card=>{
      card.hidden=!card.textContent.toLocaleLowerCase().includes(query);
    });
  });
  form.addEventListener('submit',event=>{
    const selected=Array.from(list.querySelectorAll('input[name="dish_slug"]:checked'));
    const missing=selected.find(checkbox=>!form.querySelector('input[name="dish_rating_'+CSS.escape(checkbox.value)+'"]:checked'));
    if(missing){
      event.preventDefault();
      panel.classList.add('dish-needs-attention');
      const target=form.querySelector('input[name="dish_rating_'+CSS.escape(missing.value)+'"]');
      if(target)target.focus();
      count.textContent=words[lang].missing;
      return;
    }
    submit.disabled=true;
    submit.querySelector('span').textContent=lang==='he'?'שולח…':'Sending…';
    submit.setAttribute('aria-busy','true');
  });
})();